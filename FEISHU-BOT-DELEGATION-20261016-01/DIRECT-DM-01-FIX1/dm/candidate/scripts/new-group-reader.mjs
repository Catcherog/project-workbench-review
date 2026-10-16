import {verifiedGroupMessages} from './group-chat-reader.mjs';

const fail = message => Object.assign(new Error(message), {status: 502});
/** Membership discovery is independent of project binding. The first complete
 * list is a baseline; only newly observed groups or new mentions open a window. */
export class NewGroupReader {
  constructor(client) { this.client = client; }

  async read({start, end, state = {}, triggers = [], signal, identity, isolation}) {
    const chats = new Map(), seen = new Set();
    let token = '', listed = false;
    for (let page = 0; page < 30; page++) {
      const data = await this.client.run(['im', '+chat-list', '--types', 'group', '--page-size', '100', '--as', 'user', ...(token ? ['--page-token', token] : [])], {signal});
      if (!Array.isArray(data.chats) || typeof data.has_more !== 'boolean') throw fail('新群发现列表不完整，未更新群范围');
      for (const chat of data.chats) {
        if (!/^oc_[\w-]+$/.test(chat.chat_id || '')) throw fail('新群身份无法核对');
        chats.set(chat.chat_id, {id: chat.chat_id, name: chat.name || '新发现的群聊'});
      }
      if (!data.has_more) { listed = true; break; }
      if (!data.page_token || seen.has(data.page_token)) throw fail('新群列表分页异常，未更新群范围');
      token = data.page_token; seen.add(token);
    }
    if (!listed) throw fail('新群列表超过本轮范围，未将缺失群误认为退出');
    const next = structuredClone(state), previous = new Set(state.membershipIds || []);
    next.groups ||= {};
    const add = (chatId, since, trigger) => {
      if (!chats.has(chatId) || next.groups[chatId]) return;
      next.groups[chatId] = {...chats.get(chatId), since, through: since, trigger, discoveredAt: end};
    };
    if (state.listedAt) for (const id of chats.keys()) {
      if (!previous.has(id)) add(id, state.listedAt, '首次发现加入的群');
    }
    for (const message of triggers.filter(message=>!isolation?.hold({identity,message,channel:'group_trigger'}))) add(message.chat_id, new Date(Math.max(Date.parse(start), Number(message.create_time))).toISOString(), '新收到的群内@消息');
    next.membershipIds = [...chats.keys()]; next.listedAt = end;
    for (const group of Object.values(next.groups)) group.unavailable = !chats.has(group.id);
    const messages = [], issues = [];
    const pending = Object.values(next.groups).filter(group => !group.unavailable).sort((a, b) => (a.lastAttemptAt || '').localeCompare(b.lastAttemptAt || '') || a.id.localeCompare(b.id));
    for (const group of pending.slice(0, 5)) {
      group.lastAttemptAt = end;
      const from = new Date(Math.max(Date.parse(group.since), Date.parse(group.through) - 60000)).toISOString();
      const until = new Date(Math.min(Date.parse(end), Date.parse(from) + (group.windowSeconds || 3600) * 1000)).toISOString();
      let pageToken = '', complete = false; const tokens = new Set(), rows = [];
      try {
        for (let page = 0; page < 10; page++) {
          const data = await this.client.run(['im', '+chat-messages-list', '--chat-id', group.id, '--start', from, '--end', until, '--order', 'asc', '--page-size', '50', '--no-reactions', '--as', 'user', ...(pageToken ? ['--page-token', pageToken] : [])], {signal});
          if (!Array.isArray(data.messages) || typeof data.has_more !== 'boolean') throw fail('群消息分页不完整');
          rows.push(...await verifiedGroupMessages(this.client, data.messages, group.id, {signal}));
          if (!data.has_more) { complete = true; break; }
          if (!data.page_token || tokens.has(data.page_token)) throw fail('群消息分页游标异常');
          pageToken = data.page_token; tokens.add(pageToken);
        }
        for (const row of rows) if (Number(row.create_time) >= Date.parse(group.since) && Number(row.create_time) <= Date.parse(until)) {
          if(isolation?.hold({identity,message:row,channel:'group_discovery'}))continue;
          messages.push({...row, chat_name: group.name, channels: ['group-discovery'], discovery: {trigger: group.trigger, discoveredAt: group.discoveredAt}, message_app_link: row.message_app_link || 'https://applink.feishu.cn/client/chat/open?openChatId=' + group.id});
        }
        if (complete) {
          group.through = until; group.error = ''; group.windowSeconds = Math.min(3600, (group.windowSeconds || 3600) * 2);
        } else {
          group.windowSeconds = Math.max(30, Math.floor((group.windowSeconds || 3600) / 2));
          throw fail('群消息超出分页范围，保留原读取位置并缩小窗口续读');
        }
      } catch (error) {
        if (signal?.aborted) throw error;
        group.error = error.message; issues.push(group.name + '：' + error.message);
      }
    }
    return {state: next, messages, issues};
  }
}
