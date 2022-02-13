from ml.data.datasets import StarWars
from typing import Optional, Dict, Tuple, Any

import torch
import torch.nn.functional as F
from torch_geometric.typing import Metadata
from torch_geometric.nn import HGTConv, Linear
import torchmetrics
import pytorch_lightning as pl
import math

import torch_geometric.nn as tg_nn

from shared.constants import BENCHMARKS_RESULTS
from shared.graph import DataGraph
from benchmarks.evaluation import get_metric_list
from shared.schema import GraphSchema, DatasetSchema
from shared.graph import CommunityAssignment
import pandas as pd
from datasets.scripts import export_to_visualization

import ml

dataset = StarWars()
data = dataset[0]
data

node_type = 'Character'
embedding_dim = 32
data_module = ml.EdgeLoaderDataModule(
    data,
    batch_size=16, num_samples=[4] * 2,
    num_workers=0, node_type=node_type, neg_sample_ratio=1
)

embedding_module = tg_nn.Sequential('x, edge_index', [
    (tg_nn.SAGEConv((-1, -1), embedding_dim), 'x, edge_index -> x'),
    torch.nn.ReLU(inplace=True),
    (tg_nn.SAGEConv((-1, -1), embedding_dim), 'x, edge_index -> x'),
])
embedding_module = tg_nn.to_hetero(embedding_module, data.metadata(), aggr='mean')


class ClusteringModule(torch.nn.Module):
    def __init__(
            self, rep_dim: int, n_clusters: int,
            cluster_centers: Optional[torch.Tensor] = None
    ):
        super().__init__()
        self.n_clusters = n_clusters
        self.rep_dim = rep_dim

        if cluster_centers is None:
            initial_cluster_centers = torch.zeros(
                self.n_clusters, self.rep_dim, dtype=torch.float
            )
            torch.nn.init.xavier_uniform_(initial_cluster_centers)
        else:
            assert cluster_centers.shape == (self.n_clusters, self.rep_dim)
            initial_cluster_centers = cluster_centers
        self.cluster_centers = torch.nn.Parameter(initial_cluster_centers)
        self.cos_sim = torch.nn.CosineSimilarity(dim=2)
        self.activation = torch.nn.Softmax(dim=1)

    def forward(self, batch: torch.Tensor):
        sim = self.cos_sim(batch.unsqueeze(1), self.cluster_centers.unsqueeze(0))
        return self.activation(sim)

    def forward_assign(self, batch: torch.Tensor):
        q = self(batch)
        return q.argmax(dim=1)


class LinkPredictionLoss(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.ce_loss = torch.nn.CrossEntropyLoss()

    def forward(self, pred: torch.Tensor, label: torch.Tensor):
        return self.ce_loss(pred, label)


class ClusteringLoss(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.ce_loss = torch.nn.CrossEntropyLoss()
        self.cos_sim = torch.nn.CosineSimilarity(dim=1)

    def forward(self, q_l: torch.Tensor, q_r: torch.Tensor, label: torch.Tensor):
        p = torch.sum(q_l, dim=0) + torch.sum(q_r, dim=0)
        p /= p.sum()
        ne = math.log(p.size(0)) + (p * torch.log(p)).sum()

        sim = (self.cos_sim(q_l, q_r) + 1) / 2
        pred = torch.stack([1 - sim, sim], dim=1)
        loss = self.ce_loss(pred, label)

        return loss, ne


class Net(ml.BaseModule):
    def __init__(
            self,
            node_type: str,
            embedding_module: torch.nn.Module,
            clustering_module: ClusteringModule,
    ):
        super().__init__()
        self.node_type = node_type
        self.embedding_module = embedding_module
        self.clustering_module = clustering_module
        self.cos_sim = torch.nn.CosineSimilarity(dim=1)
        self.lin = torch.nn.Linear(1, 2)

        self.link_prediction_loss = LinkPredictionLoss()
        self.clustering_loss = ClusteringLoss()

        self.is_pretraining = True

    def configure_metrics(self) -> Dict[str, Tuple[torchmetrics.Metric, bool]]:
        return {
            'loss': (torchmetrics.MeanMetric(), True),
            'hp_loss': (torchmetrics.MeanMetric(), True),
            'cc_loss': (torchmetrics.MeanMetric(), True),
            'accuracy': (torchmetrics.Accuracy(), True),
            'ne': (torchmetrics.MeanMetric(), True),
        }

    def _step(self, batch: torch.Tensor):
        batch_l, batch_r, label = batch
        batch_size = batch_l[self.node_type].batch_size

        emb_l = self.embedding_module(batch_l.x_dict, batch_l.edge_index_dict)[self.node_type][:batch_size]
        emb_r = self.embedding_module(batch_r.x_dict, batch_r.edge_index_dict)[self.node_type][:batch_size]
        sim = self.cos_sim(emb_l, emb_r)
        out = self.lin(torch.unsqueeze(sim, 1))
        hp_loss = self.link_prediction_loss(out, label)

        out_dict = {}
        if self.is_pretraining:
            loss = hp_loss
        else:
            q_l = self.clustering_module(emb_l)
            q_r = self.clustering_module(emb_r)
            cc_loss, ne = self.clustering_loss(q_l, q_r, label)
            loss = hp_loss + 2 * cc_loss + ne * 0.01
            out_dict['ne'] = ne
            out_dict['cc_loss'] = cc_loss

        pred = out.argmax(dim=-1)
        return {
            'loss': loss,
            'hp_loss': hp_loss,
            'accuracy': (pred, label),
            **out_dict
        }

    def forward(self, batch):
        batch_size = batch[self.node_type].batch_size
        emb = self.embedding_module(batch.x_dict, batch.edge_index_dict)[self.node_type][:batch_size]
        q = self.clustering_module(emb)
        return emb, q

    def training_step(self, batch):
        return self._step(batch)

    def validation_step(self, batch, batch_idx):
        return self._step(batch)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=1e-3)
        return optimizer


clustering_module = ClusteringModule(rep_dim=32, n_clusters=5)
model = Net(node_type, embedding_module, clustering_module)

model.is_pretraining = True
trainer = pl.Trainer(
    gpus=1,
    callbacks=[
        pl.callbacks.EarlyStopping(monitor="val/loss", min_delta=0.00, patience=5, verbose=True, mode="min")
    ],
    max_epochs=20,
    enable_model_summary=True,
    # logger=wandb_logger
)
trainer.fit(model, data_module)

model.is_pretraining = False
trainer = pl.Trainer(
    gpus=1,
    callbacks=[
        pl.callbacks.EarlyStopping(monitor="val/loss", min_delta=0.00, patience=5, verbose=True, mode="min")
    ],
    max_epochs=20,
    enable_model_summary=True,
    # logger=wandb_logger
)
trainer.fit(model, data_module)

save_path = BENCHMARKS_RESULTS.joinpath('analysis', 'pyg-sage-comopt-contrastive')
save_path.mkdir(parents=True, exist_ok=True)

predictions = trainer.predict(model, data_module)
embeddings, assignments = map(lambda x: torch.cat(x, dim=0).detach().cpu(), zip(*predictions))
assignments = torch.argmax(assignments, dim=1)

labeling = pd.Series(assignments.squeeze(), index=dataset.node_mapping(), name="cid")
labeling.index.name = "nid"
comlist = CommunityAssignment(labeling)
comlist.save_comlist(save_path.joinpath('schema.comlist'))

export_to_visualization.run(
    export_to_visualization.Args(
        dataset='star-wars',
        version='base',
        run_paths=[str(save_path)]
    )
)

# Calculate Evaluation Metrics
DATASET = DatasetSchema.load_schema('star-wars')
schema = GraphSchema.from_dataset(DATASET)
G = DataGraph.from_schema(schema)

metrics = get_metric_list(ground_truth=False, overlapping=False)

results = pd.DataFrame([
    {
        'metric': metric_cls.metric_name(),
        'value': metric_cls.calculate(G, comlist)
    }
    for metric_cls in metrics]
)
print(results)
