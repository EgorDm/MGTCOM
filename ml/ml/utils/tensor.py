import sys
from typing import Union, List, Dict

import numpy as np
import torch
from torch import Tensor


def partition_values(vs, ranges):
    partitions = []
    for i, (start, end) in enumerate(ranges):
        size = int(torch.sum((vs >= start) & (vs < end)))
        partitions.append(size)

    partitions = torch.sort(vs).values.split(partitions)

    return partitions


def randint_range(range: Tensor, low=None, dtype=torch.long):
    size = range.size()

    out = torch.randint(0, sys.maxsize, size=size, dtype=dtype) % range
    if low is not None:
        out = out + low
    return out


def ensure_numpy(x: Union[Tensor, np.ndarray]) -> np.ndarray:
    if isinstance(x, Tensor):
        return x.detach().cpu().numpy()
    else:
        return x


def unique_count(z: Tensor, k: int) -> Tensor:
    """
    Counts the number of elements in each of the k partitions.
    """
    return torch.bincount(z, minlength=k)


def scatter_sum(X: Tensor, z: Tensor, k: int) -> Tensor:
    return torch.zeros(k, X.shape[1], device=X.device).index_add_(0, z, X)


def tensor_partition(X: Tensor, z: Tensor, k: int) -> List[Tensor]:
    return [X[z == i] for i in range(k)]


def mask_from_idx(idx: Tensor, n: int) -> Tensor:
    """
    Creates a mask from an index vector.
    """
    mask = torch.zeros(n, dtype=torch.bool)
    mask[idx] = True
    return mask


def dict_catv(d: Dict[str, Tensor], dim=0) -> Tensor:
    return torch.cat(list(d.values()), dim=dim)


def batchwise_outer(x: Tensor, y: Tensor) -> Tensor:
    return torch.einsum('bi,bj->bij', (x, y))
