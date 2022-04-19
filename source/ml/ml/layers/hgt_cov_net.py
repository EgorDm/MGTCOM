from dataclasses import dataclass
from typing import Optional, Dict

import torch
from torch import Tensor
from torch_geometric.data import HeteroData
from torch_geometric.nn import HGTConv
from torch_geometric.typing import Metadata, NodeType

from ml.utils import HParams


@dataclass
class HGTConvNetParams(HParams):
    hidden_dim: Optional[int] = None

    num_layers: int = 2
    num_heads: int = 2


class HGTConvNet(torch.nn.Module):
    def __init__(
            self,
            repr_dim: int,
            metadata: Metadata,
            hparams: HGTConvNetParams = None
    ) -> None:
        super().__init__()
        self.hparams = hparams or HGTConvNetParams()
        self.repr_dim = repr_dim
        self.hidden_dim = self.hparams.hidden_dim or repr_dim

        self.convs = torch.nn.ModuleList()
        for i in range(self.hparams.num_layers):
            out_dim = self.hidden_dim if i < self.hparams.num_layers - 1 else self.repr_dim
            self.convs.extend([
                HGTConv(self.hidden_dim, out_dim, metadata, self.hparams.num_heads, group='mean')
            ])

    def forward(self, data: HeteroData, X_dict: Dict[NodeType, Tensor] = None) -> Dict[NodeType, Tensor]:
        Z_dict = X_dict or data.x_dict

        # Apply convolutions
        for conv in self.convs:
            Z_dict = conv(Z_dict, data.edge_index_dict)

        # Return node represenations
        return {
            node_type: Z_dict[node_type][:batch_size]
            for node_type, batch_size in data.batch_size_dict.items()
        }
