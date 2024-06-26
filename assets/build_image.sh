#!/usr/bin/env bash

# Args:
# $1: the library for which you would like to build a container
# -p ($2): whether to prune docker system before building anything.
# -r ($3): whether to run the library container after build
# Run at root of repo!

lib="$1"
run_="$2" # -r
prune="$3"  # -p


if [ "$prune" ]; then
  yes | docker system prune -a
fi

cd bio_check/"$lib" || exit
docker build -t ghcr.io/biosimulators/bio-check-"$lib" .

if [ "$run_" ]; then
  echo "Running container for $lib"
  ./run_container.sh "$lib"
fi