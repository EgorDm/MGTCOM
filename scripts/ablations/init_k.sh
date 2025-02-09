source activate.sh

ARGS_CMD="python ml/ml/executors"
ARGS_BASE="--project=MGTCOM --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=100 --classification_eval.interval=100 --clustering_visualizer.interval=100"

EXPERIMENT="$ARGS_CMD/mgcom_comdet_executor.py --dataset=DBLPHCN --experiment=ablation_initk2 $ARGS_BASE --max_epochs=200 --batch_size=400 --prior_sigma_scale=0.0005 --prior_alpha=10 \
  --pretrained_path=/data/pella/projects/University/Thesis/Thesis/source/config/ablations/embeddings_hetero_combi.pt --cpu --offline"

#$(echo $EXPERIMENT) --run_name="feat" $(echo $ARGS_DS)
#$(echo $EXPERIMENT) --run_name="k64" --init_k=64
#$(echo $EXPERIMENT) --run_name="k32" --init_k=32
#$(echo $EXPERIMENT) --run_name="k1" --init_k=1
#$(echo $EXPERIMENT) --run_name="k3" --init_k=2
$(echo $EXPERIMENT) --run_name="k8" --init_k=8
#$(echo $EXPERIMENT) --run_name="k16" --init_k=16
