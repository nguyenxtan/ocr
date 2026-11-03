"""Web-only seal candidates, including black/gray photocopies.

Geometry cannot distinguish a seal from a similar logo. Monochrome candidates
always stay below the automatic-presence threshold; scores are ranking signals,
not probabilities. The Telegram detector and its callers are unchanged.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.analysis import detect_stamps as red_stamps


def monochrome_ink(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 41, 9)
    ink[(saturation > 55) | (gray > 225)] = 0
    return ink


def monochrome_stamps(rgb):
    height, width = rgb.shape[:2]
    scale = min(1., 1000 / max(height, width))
    small = cv2.resize(rgb, (round(width*scale), round(height*scale)),
                       interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    ink = monochrome_ink(small)
    sh, sw = ink.shape
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(joined, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    shapes = []
    for contour in contours:
        if len(contour) >= 60:
            shapes.append((cv2.fitEllipse(contour), contour))
    # A signature or table line crossing a ring joins contours together. Hough
    # voting recovers circular rings without requiring an isolated closed contour.
    votes = ink.copy()
    for kernel in ((max(30, sw//10), 1), (1, max(30, sh//10))):
        lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones(kernel[::-1], np.uint8))
        votes = cv2.subtract(votes, lines)
    circles = cv2.HoughCircles(cv2.GaussianBlur(votes, (5, 5), 0), cv2.HOUGH_GRADIENT,
        dp=1.4, minDist=max(20, min(sh, sw)*.025), param1=80, param2=45,
        minRadius=max(20, int(min(sh, sw)*.035)), maxRadius=int(min(sh, sw)*.22))
    if circles is not None:
        shapes.extend((((float(x),float(y)),(float(r*2),float(r*2)),0.),None)
                      for x,y,r in np.rint(circles[0]))
    candidates = []
    theta = np.linspace(0, 2*np.pi, 96, endpoint=False)
    offsets = np.arange(-2, 3)
    for ((cx, cy), (d1, d2), angle), contour in shapes:
        major, minor = max(d1, d2), min(d1, d2)
        if not min(sh, sw)*.065 <= minor <= major <= min(sh, sw)*.44:
            continue
        if major/minor > 1.8:
            continue
        alpha = np.deg2rad(angle)
        cos, sin = np.cos(alpha), np.sin(alpha)
        # Reject rectangular table borders: their contours do not follow an ellipse.
        if contour is not None:
            points = contour[:, 0, :] - (cx, cy)
            u = (points[:, 0]*cos + points[:, 1]*sin)/(d1/2)
            v = (-points[:, 0]*sin + points[:, 1]*cos)/(d2/2)
            if np.quantile(np.abs(np.hypot(u, v)-1), .9) > .07:
                continue

        def coverage(factor):
            dx = (d1/2*factor + offsets[:, None])*np.cos(theta)
            dy = (d2/2*factor + offsets[:, None])*np.sin(theta)
            x = np.rint(cx + dx*cos - dy*sin).astype(int)
            y = np.rint(cy + dx*sin + dy*cos).astype(int)
            valid = (x >= 0) & (x < sw) & (y >= 0) & (y < sh)
            hit = valid & (ink[np.clip(y, 0, sh-1), np.clip(x, 0, sw-1)] > 0)
            return np.any(hit, axis=0).mean()

        outer = coverage(1)
        if outer < .85:
            continue
        factor, inner = max(((f, coverage(f)) for f in (.70,.74,.78,.82,.86,1.18,1.28,1.38)),
                            key=lambda item:item[1])
        if outer < .85 or inner < .70:
            continue
        # Empty concentric circles and solid circular logos are not useful evidence.
        extent = int(np.ceil(major*.6*max(1, factor)))
        left, top = max(0, int(cx)-extent), max(0, int(cy)-extent)
        right, bottom = min(sw, int(cx)+extent), min(sh, int(cy)+extent)
        if left >= right or top >= bottom:
            continue
        central = np.zeros((bottom-top, right-left), np.uint8)
        cv2.ellipse(central, (round(cx-left), round(cy-top)),
                    (round(d1*.30), round(d2*.30)), angle, 0, 360, 255, -1)
        count = cv2.countNonZero(central)
        density = cv2.countNonZero(cv2.bitwise_and(ink[top:bottom, left:right], central))/max(1, count)
        if not .008 <= density <= .35:
            continue
        # Map independently on each axis: resize rounding must not shift sources.
        box = (max(0, int(left*width/sw)), max(0, int(top*height/sh)),
               min(width, int(np.ceil(right*width/sw))), min(height, int(np.ceil(bottom*height/sh))))
        candidates.append((outer+inner, box))
    selected = []
    for _, box in sorted(candidates, reverse=True):
        if any(same_region(box, previous[2]) for previous in selected):
            continue
        x0, y0, x1, y1 = box
        selected.append((.60, monochrome_ink(rgb[y0:y1, x0:x1]), box))
        if len(selected) == 3:
            break
    return selected


def same_region(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, right-left)*max(0, bottom-top)
    smaller = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
    return intersection > .6*smaller


def detect_stamps(rgb, max_candidates=3, *, with_boxes=False):
    selected = list(red_stamps(rgb, max_candidates=max_candidates, with_boxes=True))
    # Run even when a red seal exists; another page region may be photocopied.
    for candidate in monochrome_stamps(rgb):
        if not any(same_region(candidate[2], old[2]) for old in selected):
            selected.append(candidate)
    selected = selected[:max_candidates]
    return selected if with_boxes else [(score, mask) for score, mask, _ in selected]
