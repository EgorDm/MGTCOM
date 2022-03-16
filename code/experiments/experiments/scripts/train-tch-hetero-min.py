import pytorch_lightning as pl
import torch
from torch_geometric.transforms import ToUndirected

from ml import SortEdges, newman_girvan_modularity
from ml.datasets import IMDB5000, StarWars, DBLPHCN
from ml.layers import ExplicitClusteringModule
from ml.layers.embedding import HGTModule
from ml.models.positional import PositionalModel, PositionalDataModule
from ml.utils.collections import merge_dicts

# dataset = StarWars()
# batch_size = 16
# n_clusters = 5
dataset = IMDB5000()
batch_size = 512
n_clusters = 50
# dataset = DBLPHCN()
# batch_size = 512
# n_clusters = 55

data = dataset.data
data = ToUndirected(reduce='max')(data)
data = SortEdges()(data)

lr = 0.01
# repr_dim = 32
repr_dim = 64
# n_epochs = 20
# n_comm_epochs = 10
n_epochs = 8
n_comm_epochs = 6
# n_epochs = 1
# n_comm_epochs = 1
num_samples = [4, 3]
num_neg_samples = 4
use_Lin = True
ne_weight = 0.0001

temporal = False
gpus = 1
workers = 8

data_module = PositionalDataModule(
    data, num_samples=num_samples, num_neg_samples=num_neg_samples, batch_size=batch_size, temporal=temporal,
    num_workers=workers, prefetch_factor=4, persistent_workers=True
)

# embedding_module = PinSAGEModule(data.metadata(), repr_dim, normalize=False)
in_channels = {
    node_type: data[node_type].num_features
    for node_type in data.node_types
}
embedding_module = HGTModule(data.metadata(), in_channels, repr_dim, num_heads=2, num_layers=2, use_RTE=temporal, use_Lin=use_Lin)
clustering_module = ExplicitClusteringModule(repr_dim, n_clusters)
model = PositionalModel(embedding_module, clustering_module, lr=lr, ne_weight=ne_weight)

# Pretraining
trainer = pl.Trainer(gpus=gpus, min_epochs=n_epochs, max_epochs=n_epochs)
trainer.fit(model, data_module)
# Cluster-aware training
model.use_clustering = True
trainer = pl.Trainer(gpus=gpus, min_epochs=n_comm_epochs, max_epochs=n_comm_epochs, enable_model_summary=False)
trainer.fit(model, data_module)

# Get Embeddings
pred = trainer.predict(model, data_module)
embeddings = merge_dicts(pred, lambda xs: torch.cat(xs, dim=0))

print('Reusing trained centers')
emb_q = {k: clustering_module(emb) for k, emb in embeddings.items()}
I = {k: q.argmax(dim=-1) for k, q in emb_q.items()}

m = newman_girvan_modularity(data, I, n_clusters)
print(f'Modularity: {m:.4f}')