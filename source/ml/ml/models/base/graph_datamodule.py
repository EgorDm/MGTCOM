import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Union, Tuple

import pytorch_lightning as pl
from torch import Tensor
from torch_geometric.data import HeteroData, Data
from torch_geometric.typing import Metadata, NodeType

from datasets import GraphDataset
from datasets.utils.base import Snapshots
from datasets.transforms.ensure_timestamps import EnsureTimestampsTransform
from datasets.utils.labels import NodeLabelling
from ml.data.transforms.eval_split import EvalNodeSplitTransform
from datasets.transforms.to_homogeneous import to_homogeneous
from ml.evaluation import extract_edge_prediction_pairs
from ml.utils import HParams, DataLoaderParams
from shared import get_logger

logger = get_logger(Path(__file__).stem)


@dataclass
class GraphDataModuleParams(HParams):
    lp_max_pairs: int = 5000
    train_on_full_data: bool = False


class GraphDataModule(pl.LightningDataModule):
    dataset: GraphDataset
    hparams: Union[GraphDataModuleParams, DataLoaderParams]
    loader_params: DataLoaderParams

    train_data: Union[HeteroData, Data]
    val_data: Union[HeteroData, Data]
    test_data: Union[HeteroData, Data]
    heterogenous: bool = True

    def __init__(
            self,
            dataset: GraphDataset,
            hparams: GraphDataModuleParams,
            loader_params: DataLoaderParams,
    ) -> None:
        super().__init__()
        self.save_hyperparameters(hparams.to_dict())
        self.save_hyperparameters(loader_params.to_dict())
        self.loader_params = loader_params

        self.dataset = dataset
        self.data = EnsureTimestampsTransform(warn=True)(dataset.data)
        if self.train_on_full_data or self.hparams.train_on_full_data:
            logger.warning("Using full dataset for training. There is no validation or test set.")
            self.train_data, self.val_data, self.test_data = self.data, self.data, self.data
        else:
            self.train_data, self.val_data, self.test_data = EvalNodeSplitTransform()(self.data)

        logger.info('=' * 80)
        logger.info(f'Using dataset {self.dataset.name}')
        logger.info(str(self.data))
        logger.info('=' * 80)

    @property
    def metadata(self) -> Metadata:
        return self.dataset.metadata

    @property
    def num_nodes_dict(self) -> Dict[NodeType, int]:
        return self.train_data.num_nodes_dict

    @property
    def snapshots(self) -> Optional[Dict[int, Snapshots]]:
        if isinstance(self.dataset, GraphDataset) and self.dataset.snapshots is not None:
            return self.dataset.snapshots
        return None

    def _edge_prediction_pairs(self, data: Union[HeteroData, Data], mask_name: str = 'train_mask') -> Tuple[
        Tensor, Tensor]:
        """
        It takes a heterogeneous graph and returns a tuple of two tensors, the edges and the edge labels.

        :param data: HeteroData
        :type data: HeteroData
        :param mask_name: The name of the edge mask attribute, defaults to train_mask
        :type mask_name: str (optional)
        """
        if isinstance(data, HeteroData):
            hdata = to_homogeneous(
                data,
                node_attrs=[], edge_attrs=[mask_name],
                add_node_type=False, add_edge_type=False
            )
        else:
            hdata = data

        return extract_edge_prediction_pairs(
            hdata.edge_index, hdata.num_nodes, getattr(hdata, f'edge_{mask_name}'),
            max_samples=self.hparams.lp_max_pairs
        )

    def train_prediction_pairs(self) -> Tuple[Tensor, Tensor]:
        return self._edge_prediction_pairs(self.train_data, 'train_mask')

    def val_prediction_pairs(self) -> Tuple[Tensor, Tensor]:
        return self._edge_prediction_pairs(self.val_data, 'val_mask')

    def test_prediction_pairs(self) -> Tuple[Tensor, Tensor]:
        return self._edge_prediction_pairs(self.test_data, 'test_mask')

    def _extract_inferred_labels(
            self, data: HeteroData
    ) -> Dict[str, NodeLabelling]:
        node_labels = {}
        for label in self.dataset.labels():
            node_labels[label] = getattr(data, f'{label}_dict')

        return node_labels

    @lru_cache(maxsize=1)
    def train_inferred_labels(self) -> Dict[str, NodeLabelling]:
        return self._extract_inferred_labels(self.train_data)

    @lru_cache(maxsize=1)
    def val_inferred_labels(self) -> Dict[str, NodeLabelling]:
        return self._extract_inferred_labels(self.val_data)

    @lru_cache(maxsize=1)
    def test_inferred_labels(self) -> Dict[str, NodeLabelling]:
        return self._extract_inferred_labels(self.test_data)

    @lru_cache(maxsize=1)
    def inferred_labels(self) -> Dict[str, NodeLabelling]:
        return self._extract_inferred_labels(self.data)

    @property
    def train_on_full_data(self):
        return False
