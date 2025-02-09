source activate.sh

ARGS_CMD="python ml/ml/executors"
ARGS_BASE="--project=MGTCOM"
ARGS_SW="--batch_size=16  --max_epochs=200 --dataset=StarWars --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"
ARGS_CORA="--batch_size=128 --max_epochs=50 --dataset=Cora --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"
ARGS_DBLP="--batch_size=128 --max_epochs=50 --dataset=DBLPHCN --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"
ARGS_IMDB="--batch_size=128 --max_epochs=50 --dataset=IMDB5000 --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"
ARGS_ICEWS="--batch_size=128 --max_epochs=50 --dataset=ICEWS0515 --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"
ARGS_SDS="--batch_size=2048 --max_epochs=40 --dataset=SocialDistancingStudents --embedding_visualizer.dim_reduction_mode=TSNE --embedding_visualizer.interval=10 --classification_eval.interval=10"

# Embeddings
EMBED_SW="--embed_node_types Character"
EMBED_CORA="--embed_node_types 0"

EMBED_DBLP="--embed_node_types Venue Author"
EMBED_DBLP_FULL="--embed_node_types Venue Author Paper"

EMBED_IMDB="--embed_node_types Genre Person"
EMBED_IMDB_FULL="--embed_node_types Genre Person Movie"

EMBED_SDS="--embed_node_types Hashtag User"
EMBED_SDS_FULL="--embed_node_types Hashtag User Tweet"

EMBED_ICEWS="--embed_node_types Entity"

EXPERIMENT="$ARGS_CMD/mgcom_tempo_executor.py --experiment=abl_metatempo2 $ARGS_BASE --lr=0.02 --repr_dim=32 --num_workers=3 --metric=DOTP"

ARGS_DS="$ARGS_DBLP"
EMBED_DS="$EMBED_DBLP"
EMBED_FULL_DS="$EMBED_DBLP"

for i in `seq 1 3`; do
  $(echo $EXPERIMENT) --run_name="sage_full" $(echo "$ARGS_DS $EMBED_FULL_DS") --conv_method=SAGE --homogenify=false
  $(echo $EXPERIMENT) --run_name="hgt_full" $(echo "$ARGS_DS $EMBED_FULL_DS") --conv_method=HGT --homogenify=false
done

for i in `seq 1 3`; do
  $(echo $EXPERIMENT) --run_name="sage_full_homo" $(echo "$ARGS_DS") --embed_node_types 0 --conv_method=SAGE --homogenify=true
  $(echo $EXPERIMENT) --run_name="hgt_full_homo" $(echo "$ARGS_DS") --embed_node_types 0 --conv_method=HGT --homogenify=true
done