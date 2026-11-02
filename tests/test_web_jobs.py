import asyncio
import fitz
import pytest
from app.web_jobs import Store


def test_real_worker_timeout_is_killed_and_cannot_publish(tmp_path):
    path=tmp_path/'input.pdf'
    with fitz.open() as doc:
        doc.new_page();doc.save(path)
    async def scenario():
        store=Store(tmp_path)
        try:
            with pytest.raises(TimeoutError):
                await store.command('extract',path,tmp_path/'result.json','gpkd','vie+eng',timeout=.001)
            assert not (tmp_path/'result.json').exists()
        finally: await store.close()
    asyncio.run(scenario())
