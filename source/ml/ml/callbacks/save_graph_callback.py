from dataclasses import dataclass
from pathlib import Path
from typing import List, Any

import torch
import wandb
from pytorch_lightning import Callback, Trainer, LightningModule

from datasets import GraphDataset
from datasets.utils.conversion import igraph_from_hetero, extract_attribute_dict
from ml.algo.clustering import KMeans
from ml.utils import Metric, HParams
from ml.utils.outputs import OutputExtractor
from shared import get_logger

logger = get_logger(Path(__file__).stem)


@dataclass
class SaveGraphCallbackParams(HParams):
    metric: Metric = Metric.DOTP
    """Metric to use for kmeans clustering."""


class SaveGraphCallback(Callback):
    def __init__(
            self,
            dataset: GraphDataset,
            hparams: SaveGraphCallbackParams = None,
            clustering: bool = False,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.hparams = hparams or SaveGraphCallbackParams()
        self.clustering = clustering

    def on_predict_epoch_end(self, trainer: Trainer, pl_module: LightningModule, outputs: List[Any]) -> None:
        outputs = OutputExtractor(outputs)
        data = self.dataset.data

        if self.clustering:
            Z = outputs.extract_cat('X', device='cpu')
        else:
            Z = outputs.extract_cat_kv('Z_dict', device='cpu')

        logger.info("Saving graph")
        allowed_attrs = ['name', 'timestamp_from', 'timestamp_to', 'train_mask', 'test_mask', 'val_mask']
        allowed_attrs.extend(self.dataset.labels())

        node_attrs = {}
        edge_attrs = {}
        for attr in allowed_attrs:
            if attr in data.keys:
                node_data = extract_attribute_dict(data, attr, edge_attr=False, error=False)
                if node_data:
                    node_attrs[attr] = node_data

                edge_data = extract_attribute_dict(data, attr, edge_attr=True, error=False)
                if edge_data:
                    edge_attrs[attr] = edge_data

        if 'name' in node_attrs:
            node_attrs['label'] = node_attrs['name']

        G, _, _, _ = igraph_from_hetero(data, node_attrs=node_attrs, edge_attrs=edge_attrs)

        logger.info('Running K-means before saving graph')
        k = len(set(G.vs['louvain'])) if 'louvain' in node_attrs else 7 # error
        k = min(k, 24)
        I = KMeans(-1, k, metric=self.hparams.metric).fit(Z).assign(Z)
        G.vs['precluster_km'] = I.numpy() # argument 'input' (position 1) must be Tensor, not dict

        if self.clustering and 'z' in outputs:
            logger.info('Saving resulting clustering')
            z = outputs.extract_cat('z')
            G.vs['mgtcom'] = z.numpy()

        save_dir = Path(wandb.run.dir) / 'graph.graphml'
        logger.info(f"Saving graph to {save_dir}")
        G.write_graphml(str(save_dir))
