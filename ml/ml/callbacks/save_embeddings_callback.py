from pathlib import Path
from typing import List, Any

import torch
import wandb
from pytorch_lightning import Callback, Trainer, LightningModule

from ml.models.base.base_model import BaseModel
from ml.utils.outputs import OutputExtractor
from shared import get_logger

logger = get_logger(Path(__file__).stem)


class SaveEmbeddingsCallback(Callback):
    def on_predict_epoch_end(self, trainer: Trainer, pl_module: BaseModel, outputs: List[Any]) -> None:
        outputs = OutputExtractor(outputs)
        saved = False
        if 'Z_dict' in outputs:
            logger.info('Saving heterogenous embeddings...')
            Z_dict = outputs.extract_cat_dict('Z_dict', device='cpu')
            self.save_embeddings(Z_dict, 'embeddings_hetero.pt')
            saved = True

        if 'Z' in outputs:
            logger.info('Saving homogeneous embeddings...')
            Z = outputs.extract_cat('Z', device='cpu')
            self.save_embeddings(Z, 'embeddings_homogeneous.pt')
            saved = True

        if not saved:
            logger.warning('No embeddings to save!')

    def save_embeddings(self, Z: Any, name: str) -> None:
        save_dir = Path(wandb.run.dir) / name
        logger.info(f'Saving embeddings in: {save_dir}')
        torch.save(Z, save_dir)
