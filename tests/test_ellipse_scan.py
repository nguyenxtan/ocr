import cv2
import numpy as np
from app.analysis import detect_stamp


def ellipse_sample(rx, ry):
    image=np.full((800,800,3),255,np.uint8)
    for factor in (1,.8):
        cv2.ellipse(image,(350,350),(round(rx*factor),round(ry*factor)),17,0,360,(180,50,50),4)
    return image


def test_elliptical_seal_after_aspect_ratio_scan():
    score,region=detect_stamp(ellipse_sample(130,70))
    assert score >= .68 and region is not None


def test_round_seal_still_detected():
    score,_=detect_stamp(ellipse_sample(100,100))
    assert score >= .68
