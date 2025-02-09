from typing import List

from torch.utils.data import DataLoader


class ChainedDataLoader:
    def __init__(self, dataloaders: List[DataLoader]):
        self.dataloaders = dataloaders

    def __len__(self):
        return sum(len(d) for d in self.dataloaders)

    def __iter__(self):
        for dataloader in self.dataloaders:
            yield from dataloader
