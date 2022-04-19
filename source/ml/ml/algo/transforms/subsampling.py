from typing import Union, Optional

import torch
from torch import Tensor


class SubsampleTransform:
    perm: Optional[Tensor]

    def __init__(self, max_points: int = 1000) -> None:
        super().__init__()
        self.max_points = max_points
        self.perm = None

    def fit(self, X: Union[Tensor, int]):
        N = X if isinstance(X, int) else len(X)
        if N > self.max_points:
            self.perm = torch.randperm(N)[:self.max_points]
        else:
            self.perm = torch.arange(N)
        return self

    def transform(self, X: Tensor) -> Tensor:
        if self.perm is None:
            self.fit(X)

        return X[self.perm]
