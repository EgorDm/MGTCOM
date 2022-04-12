from typing import Optional, Tuple, List

import numpy as np
import torch
from torch import Tensor
from sklearn.neighbors import NearestNeighbors

from ml.layers.dpm import Priors, StackedGaussianMixtureModel, GaussianMixtureModel, compute_covs_soft_assignment

SplitDecisions = Tensor
MergeDecisions = List[Tuple[int, int]]

class MHSCRules:
    """
    Metropolis-Hastings Sub-Cluster Split and Merge Moves

    See Section 5.3:
        J. Chang and J. W. Fisher III, “Parallel Sampling of DP Mixture Models using Sub-Cluster Splits,”
        in Advances in Neural Information Processing Systems, 2013, vol. 26. Accessed: Apr. 09, 2022. [Online].
        Available: https://papers.nips.cc/paper/2013/hash/bca82e41ee7b0833588399b1fcd177c7-Abstract.html

    """

    def __init__(
            self,
            prior: Priors, gmm: GaussianMixtureModel, gmm_sub: StackedGaussianMixtureModel,
            alpha: float, split_prob: Optional[float], merge_prob: Optional[float],
            min_split_points: int = 6, n_merge_neighbors=3, sim='euclidean',
    ) -> None:
        super().__init__()
        self.prior = prior
        self.gmm = gmm
        self.gmm_sub = gmm_sub
        self.alpha = alpha
        self.split_prob = split_prob
        self.merge_prob = merge_prob
        self.min_split_points = min_split_points
        self.sim = sim
        self.n_merge_neighbors = n_merge_neighbors

    def compute_log_h_split(self, X: Tensor, X_K: Tensor, N_K: Tensor, mu: Tensor, mu_sub: Tensor):
        # See Eq (21)
        N_c = sum(N_K)

        log_ll_c = self.prior.log_marginal_likelihood(X, mu)
        log_ll_K = torch.tensor([self.prior.log_marginal_likelihood(X_k, mu_sub[k, :]) for k, X_k in enumerate(X_K)])

        lgamma_N_K = [torch.lgamma(N_k) if N_k > 0 else 0 for N_k in N_K]
        lgamma_N_c = torch.lgamma(N_c)

        # Note: np.log(self.alpha) is changed to nonlog. I have a few small datasets
        H = (
                (self.alpha + sum(lgamma_N_K) + sum(log_ll_K))
                - (lgamma_N_c + log_ll_c)
        )

        print(H)
        return H, log_ll_K.argmax(dim=-1)

    def split_rule(self, X: Tensor, ri: Tensor, mu: Tensor, mu_sub: Tensor):
        # Too few points
        if len(X) < self.min_split_points + 1:
            return False

        k = len(mu_sub)
        I = ri.argmax(dim=-1)
        X_K = [X[I == i] for i in range(k)]
        N_K = torch.tensor([len(X_k) for X_k in X_K], dtype=torch.float)

        # Subclusters are too small
        if any(N_k < self.min_split_points for N_k in N_K):
            return False

        # Compute Hastings ratio
        H, _ = self.compute_log_h_split(X, X_K, N_K, mu, mu_sub)

        # Accept split if H > 0 or with probability split_prob
        split_prob = self.split_prob or torch.exp(H)
        return bool(H > 0 or split_prob > torch.rand(1))

    def merge_rule(self, X: Tensor, ri: Tensor, mus: Tensor):
        k = len(mus)
        I = ri.argmax(dim=-1)
        if len(X) != len(I):
            u = 0
        X_K = [X[I == i] for i in range(k)]
        N_K = torch.tensor([len(X_k) for X_k in X_K], dtype=torch.float)
        N_c = sum(N_K)

        # Compute combined cluster center
        if N_c > 0:
            mu = (N_K.reshape(-1, 1) * mus).sum(dim=0) / N_c  # Weighted mean
        else:
            mu = mus.mean(dim=0)

        # H_merge = 1 / H_merge
        H, max_k = self.compute_log_h_split(X, X_K, N_K, mu, mus)
        H = -H

        # Accept merge if H > 0 or with probability merge_prob
        merge_prob = self.merge_prob or torch.exp(H)
        return bool(H > 0 or merge_prob > torch.rand(1)), max_k

    def split_decisions(self, X: Tensor, r: Tensor, ri: Tensor) -> Tensor:
        decisions = torch.zeros(self.gmm.n_components, dtype=torch.bool)

        z = r.argmax(dim=-1)
        for i in range(self.gmm.n_components):
            X_k = X[z == i]
            ri_k = ri[z == i, self.gmm_sub.n_subcomponents * i: self.gmm_sub.n_subcomponents * (i + 1)]

            decisions[i] = self.split_rule(X_k, ri_k, self.gmm.mus.data[i], self.gmm_sub[i].mus.data)

        return decisions

    def merge_decisions(self, X: Tensor, r: Tensor) -> Tensor:
        # Compute probable merge candidates by merging the most neighboring subclusters
        neigh = NearestNeighbors(n_neighbors=min(self.n_merge_neighbors, self.gmm.n_components), metric=self.sim)
        neigh.fit(self.gmm.mus.data)

        candidates = []
        ds, js = neigh.kneighbors(self.gmm.mus.data, return_distance=True)
        for i in range(self.gmm.n_components):
            candidates.extend([(d, i, j) for (d, j) in zip(ds[i], js[i]) if j < i])
        candidates = list(sorted(candidates, key=lambda x: x[0]))

        # Compute merge decisions
        z = r.argmax(dim=-1)
        considered = set()
        decisions = []
        for (_, i, j) in candidates:
            # Skip if any of the clusters is already considered
            if i in considered or j in considered:
                continue

            ind = torch.logical_or(z == i, z == j)
            X_K = X[ind]
            r_K = r[ind][:, [i, j]]
            mus = self.gmm.mus.data[[i, j], :]

            decision, dominant_k = self.merge_rule(X_K, r_K, mus)
            if decision:
                considered.add(i)
                considered.add(j)
                decisions.append((i, j) if dominant_k == 0 else (j, i))

        return torch.tensor(decisions, dtype=torch.long)

    def split(self, decisions: Tensor, X: Tensor, r: Tensor, ri: Tensor):
        z = r.argmax(dim=-1)

        # Split clusters
        pi_new = self.gmm.pi.data[~decisions]
        mus_new = self.gmm.mus.data[~decisions]
        covs_new = self.gmm.covs.data[~decisions]

        pis_to_add, mus_to_add, covs_to_add = [], [], []
        for k in decisions.nonzero():
            component = self.gmm_sub[k]
            pis_to_add.append(component.pi.data)
            mus_to_add.append(component.mus.data)
            covs_to_add.append(component.covs.data)

        self.gmm.pi.data = torch.cat([pi_new, torch.cat(pis_to_add, dim=0)], dim=0)
        self.gmm.mus.data = torch.cat([mus_new, torch.cat(mus_to_add, dim=0)], dim=0)
        self.gmm.covs.data = torch.cat([covs_new, torch.cat(covs_to_add, dim=0)], dim=0)
        self.gmm.n_components = len(self.gmm.mus.data)

        # Create new subclusters
        self.gmm_sub.components = torch.nn.ModuleList([
            component for not_split, component in zip(~decisions, self.gmm_sub.components) if not_split
        ])
        for i in decisions.nonzero():
            X_k = X[z == i]
            ri_k = ri[z == i, self.gmm_sub.n_subcomponents * i: self.gmm_sub.n_subcomponents * (i + 1)]
            z_k = ri_k.argmax(dim=-1)

            for j in range(self.gmm_sub.n_subcomponents):
                X_kj = X_k[z_k == j] if sum(z_k == j) >= self.gmm_sub.n_subcomponents else None
                self.gmm_sub.add_component().initialize_params(X_kj, None, self.prior)

    def merge(self, decisions: Tensor, X: Tensor, r: Tensor, ri: Tensor):
        z = r.argmax(dim=-1)
        mask = torch.zeros(len(self.gmm), dtype=torch.bool)
        mask[decisions.flatten()] = True

        # Merge subclusters
        self.gmm_sub.components = torch.nn.ModuleList([
            component for not_merge, component in zip(~mask, self.gmm_sub.components) if not_merge
        ])
        for pair in decisions:
            (i, j) = pair
            X_k = X[torch.logical_or(z == i, z == j)]
            if len(X_k) <= self.n_merge_neighbors:
                # Too few points to merge (so use the clusters as subclusters)
                self.gmm_sub.add_component(
                    pi_init=self.gmm.pi.data[pair],
                    mus_init=self.gmm.mus.data[pair],
                    covs_init=self.gmm.covs.data[pair],
                )
            else:
                self.gmm_sub.add_component().initialize_params(X_k, None, self.prior)

        # Merge clusters
        pis_new = self.gmm.pi.data[~mask]
        mus_new = self.gmm.mus.data[~mask]
        covs_new = self.gmm.covs.data[~mask]

        pi_merged, mus_merged, covs_merged = [], [], []
        for (i, j) in decisions:
            N_k_i, N_k_j = sum(z == i), sum(z == j)
            N_k = N_k_i + N_k_j

            r_mod = r[:, [i, j]].sum(dim=-1).reshape(-1, 1)
            if N_k > 0:
                mu_new = (self.gmm.mus.data[i] * N_k_i + self.gmm.mus.data[j] * N_k_j) / N_k
                cov_new = compute_covs_soft_assignment(X, r_mod, 1, mu_new)
            else:
                mu_new = self.gmm.mus.data[[i, j], :].mean(dim=0)
                cov_new = self.gmm.covs.data[i].unsqueeze(0)

            pi_new = (self.gmm.pi[i] + self.gmm.pi[j]).reshape(1)

            r_tot = r_mod.sum(dim=0)
            cov_new = self.prior.compute_post_cov(r_tot, mu_new, cov_new)
            mu_new = self.prior.compute_post_mus(pi_new * len(r), mu_new)

            pi_merged.append(pi_new)
            mus_merged.append(mu_new)
            covs_merged.append(cov_new)

        self.gmm.pi.data = torch.cat([pis_new, torch.cat(pi_merged, dim=0)], dim=0)
        self.gmm.mus.data = torch.cat([mus_new, torch.cat(mus_merged, dim=0)], dim=0)
        self.gmm.covs.data = torch.cat([covs_new, torch.cat(covs_merged, dim=0)], dim=0)
        self.gmm.n_components = len(self.gmm.mus.data)





