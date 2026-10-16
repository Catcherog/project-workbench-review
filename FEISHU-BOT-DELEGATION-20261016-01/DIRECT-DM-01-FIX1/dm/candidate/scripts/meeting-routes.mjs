/** Mount behind local-http authorize(req, true). No external effect on GET. */
export async function meetingWorkflowAction(service, body) {
  const actions={
    'meeting-workflow-start':'create','meeting-workflow-save':'save',
    'meeting-workflow-materials':'prepareMaterials','meeting-workflow-prepare':'prepare',
    'meeting-workflow-review':'review','meeting-workflow-execute':'execute',
    'meeting-workflow-reconcile':'reconcile','meeting-workflow-minutes':'readMinutes',
  };
  const method=actions[body.action];
  if(!method)throw Object.assign(new Error('未知会议操作'),{status:400});
  return service[method](body);
}
