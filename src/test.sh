cd /home/gnb/

./tuning.sh 2 0

cd /home/gnb/dtuan/autorun_estimate/src

sudo python3 autorun_all.py --branch randforest --param 1 --num-runs 3

cd /home/gnb/dtuan/xdp-program

git reset --h

git switch quickscore

cd /home/gnb/dtuan/autorun_estimate/src

sudo python3 autorun_all.py --branch quickscore --param 1 --num-runs 3

cd /home/gnb/dtuan/xdp-program

git reset --h

git switch svm

cd /home/gnb/dtuan/autorun_estimate/src

sudo python3 autorun_all.py --branch svm --param 1 --num-runs 3

cd /home/gnb/dtuan/xdp-program

git reset --h

git switch vanilla

cd /home/gnb/dtuan/autorun_estimate/src

sudo python3 autorun_all.py --branch base --param 1 --num-runs 3

sudo python3 autorun_nn.py --branch nn --param 1 --num-runs 3
