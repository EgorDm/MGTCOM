import copy
from dataclasses import dataclass, field
from typing import List, Dict

import torch
from torch import Tensor
from torch_geometric.data import HeteroData
from torch_geometric.loader.utils import to_hetero_csc, edge_type_to_str, filter_hetero_data
from torch_geometric.typing import NodeType

from ml.data.samplers.base import Sampler
from ml.utils import HParams
from ml.utils.graph import graph_clean_keys


@dataclass
class HGTSamplerParams(HParams):
    # num_samples: Union[List[int], Dict[NodeType, List[int]]] = field(default_factory=lambda: [3, 2])
    # num_samples: List[int] = field(default_factory=lambda: [3, 2])
    num_samples: List[int] = field(default_factory=lambda: [8, 4])
    """The number of nodes to sample in each iteration and for each node type."""


class HGTSampler(Sampler):
    def __init__(self, data: HeteroData, hparams: HGTSamplerParams = None) -> None:
        super().__init__()
        self.hparams = hparams or HGTSamplerParams()
        self.data = graph_clean_keys(data, ['x', 'edge_index'])

        self.num_samples = hparams.num_samples if isinstance(hparams.num_samples, dict) \
            else {key: hparams.num_samples for key in data.node_types}
        self.num_hops = max([len(v) for v in self.num_samples.values()])
        self.sample_fn = torch.ops.torch_sparse.hgt_sample

        self.colptr_dict, self.row_dict, self.perm_dict = to_hetero_csc(data, device='cpu')

    def sample(self, node_ids_dict: Dict[NodeType, Tensor]) -> HeteroData:
        # Correct amount of samples by the batch size
        num_inputs = sum([len(v) for v in node_ids_dict.values()])
        num_samples = {
            k: [n * num_inputs for n in v]
            for k, v in self.num_samples.items()
        }

        node_dict, row_dict, col_dict, edge_dict = self.sample_fn(
            self.colptr_dict,
            self.row_dict,
            node_ids_dict,
            num_samples,
            self.num_hops,
        )

        # Bug in torch geometric tries to take not sampled edges
        for edge_type in self.data.edge_types:
            edge_type_str = edge_type_to_str(edge_type)
            if edge_type_str not in row_dict:
                row_dict[edge_type_str] = torch.tensor([], dtype=torch.long)
                col_dict[edge_type_str] = torch.tensor([], dtype=torch.long)
                edge_dict[edge_type_str] = torch.tensor([], dtype=torch.long)

        data = filter_hetero_data(self.data, node_dict, row_dict, col_dict, edge_dict, self.perm_dict)
        for node_type, batch_ids in node_ids_dict.items():
            data[node_type].batch_size = len(batch_ids)
            data[node_type].batch_perm = torch.arange(len(batch_ids))

        for node_type, node_ids in node_dict.items():
            data[node_type].node_idx = node_dict[node_type]

        data.batch_size = sum(data.batch_size_dict.values())

        return data
