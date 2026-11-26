#!/usr/bin/env bash
set -euo pipefail
task_dir=${1:?Usage: make-empty-filesystems.sh NEW_OUTPUT_DIRECTORY}
mkdir -p "$task_dir"
for task_name in userdata metadata media_data; do
    (set -C; : > "$task_dir/$task_name.img")
done
truncate -s 2G "$task_dir/userdata.img"
truncate -s 16M "$task_dir/metadata.img" "$task_dir/media_data.img"
mkfs.f2fs -f -l userdata "$task_dir/userdata.img"
mkfs.ext4 -q -F -L metadata "$task_dir/metadata.img"
mkfs.fat -F 16 -n ANDROID_OEM "$task_dir/media_data.img"
