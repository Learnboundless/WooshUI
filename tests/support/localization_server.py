"""Isolated browser-test backend. Uses synthetic audio; never loads production models."""
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["WOOSH_SPEECH_WORKER_FAKE"] = "1"
os.environ["WOOSH_ASR_WORKER_FAKE"] = "1"
os.environ["WOOSH_MUSIC_WORKER_FAKE"] = "1"
os.environ.pop("WOOSH_STUDIO_TOKEN", None)
os.environ.pop("WOOSH_STUDIO_OFFLINE_MODELS", None)
os.environ.pop("WOOSH_STUDIO_TRANSLATION_ARCHIVE", None)

import uvicorn
from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app
import woosh_studio.system as system

system.torch_capabilities = lambda: (False, None, None)
app = create_app(StudioPaths(Path(os.environ["WOOSH_TEST_DIR"]) / "backend"))
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:1427"], allow_methods=["*"], allow_headers=["*"])
original_lifespan = app.router.lifespan_context

@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        studio = application.state.studio
        studio.models.is_installed = lambda _model: True
        import numpy as np
        studio.inference._load_model = lambda *args: object()
        def synthesize(**params):
            samples=np.arange(48000,dtype=np.float32)/48000
            tone=np.sin(2*np.pi*(440+(params["seed"]%3)*220)*samples)*0.25
            return np.concatenate([np.zeros(4800,dtype=np.float32),tone,np.zeros(4800,dtype=np.float32)])
        studio.inference._generate_one = synthesize
        original_list = studio.models.list_models
        studio.models.list_models = lambda: [model.model_copy(update={"installed":True}) for model in original_list()]
        studio.dialogue.translate = lambda text, source, target: {"source_text":text,"source_language":source,"target_language":target,"text":f"{target}: {text}","model_id":"browser-test-translation"}
        yield
app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=8767)
