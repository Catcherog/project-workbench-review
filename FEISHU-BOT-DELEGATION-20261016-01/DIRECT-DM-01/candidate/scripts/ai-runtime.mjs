const models = [
  { id: 'gpt-6.1-sol', name: 'GPT-6.1 Sol', efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'] },
  { id: 'gpt-6-astra', name: 'GPT-6 Astra', efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'] },
];
export const defaultRuntime = Object.freeze({ model: 'gpt-6.1-sol', effort: 'low' });
const fail = (message, status = 422) => Object.assign(new Error(message), { status });
export function validateRuntime(value) {
  if (!value || Object.keys(value).some(k => !['model', 'effort'].includes(k)) || !models.find(m => m.id === value.model)?.efforts.includes(value.effort)) throw fail('请选择支持的模型与思考强度');
  return { model: value.model, effort: value.effort };
}
export function runtimeArgs(value = defaultRuntime) {
  const { model, effort } = validateRuntime(value);
  return ['--model', model, '-c', `model_reasoning_effort="${effort}"`, '-c', 'service_tier="default"'];
}
export class AIRuntimeSettings {
  constructor(store) { this.store = store; }
  get() {
    return this.store.getSetting('aiRuntime') || { revision: 0, chat: { ...defaultRuntime }, background: { ...defaultRuntime }, updatedAt: null };
  }
  view() { return { ...this.get(), models, speed: 'default' }; }
  profile(name) { return validateRuntime(this.get()[name]); }
  update(input) {
    const chat = validateRuntime(input.chat), background = validateRuntime(input.background);
    return this.store.transaction(() => {
      const before = this.get();
      if (input.revision !== before.revision) throw fail('模型设置已被其他窗口修改，请刷新后重试', 409);
      this.store.setSetting('aiRuntime', { revision: before.revision + 1, chat, background, updatedAt: new Date().toISOString() });
      return this.view();
    });
  }
}
