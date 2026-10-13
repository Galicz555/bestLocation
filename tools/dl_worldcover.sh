#!/bin/sh
cd "$(dirname "$0")/.." && mkdir -p data/raw/worldcover && cd data/raw/worldcover || exit 1
for t in N45E015 N45E018 N45E021 N48E015 N48E018 N48E021; do
  f="ESA_WorldCover_10m_2021_v200_${t}_Map.tif"
  [ -s "$f" ] && { echo "$t already"; continue; }
  curl -sS --max-time 900 -o "$f" \
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/$f" \
    && echo "$t ok $(du -h "$f" | cut -f1)"
done
echo "worldcover done"
