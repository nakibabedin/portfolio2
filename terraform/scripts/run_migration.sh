#!/usr/bin/env bash
# Runs the migration task once and streams its log; exits with the task's exit
# code. Usage, from terraform/:
#
#   scripts/run_migration.sh rehearse
#   scripts/run_migration.sh final
set -euo pipefail

mode="${1:?usage: run_migration.sh rehearse|final}"
cfg=$(terraform output -raw migrate_run_config)
get() { python -c "import json,sys; v=json.loads(sys.argv[1])[sys.argv[2]]; print(','.join(v) if isinstance(v, list) else v)" "$cfg" "$1"; }

cluster=$(get cluster)
log_group=$(get logGroup)

task_arn=$(aws ecs run-task \
  --cluster "$cluster" \
  --task-definition "$(get taskDefinition)" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(get subnets)],securityGroups=[$(get securityGroups)],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"migrate\",\"environment\":[{\"name\":\"MODE\",\"value\":\"$mode\"}]}]}" \
  --query 'tasks[0].taskArn' --output text)
task_id="${task_arn##*/}"
echo "started $task_id ($mode); waiting for it to finish..."

aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"

aws logs get-log-events --log-group-name "$log_group" \
  --log-stream-name "migrate/migrate/$task_id" --start-from-head \
  --query 'events[].message' --output text | tr '\t' '\n'

read -r code reason < <(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query 'tasks[0].[containers[0].exitCode, stoppedReason]' --output text)
echo "exit code: $code ($reason)"
[[ "$code" == "0" ]]
