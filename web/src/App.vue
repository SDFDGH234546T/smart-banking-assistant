<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const senderId = ref('CUS00000001')
const draftMessage = ref('')
const isSending = ref(false)
const errorMessage = ref('')
const messages = ref([])
const messagesContainer = ref(null)

const accounts = ref([])
const transactions = ref([])
const isLoadingSidebar = ref(false)
const sidebarError = ref('')
const activeTab = ref('accounts')

const BANK_HEADERS = {
  Authorization: 'Bearer EMP000006',
  'X-Channel-Code': 'MOBILE_BANK',
}

const TXN_TYPE_LABELS = {
  deposit: '充值/存入',
  withdraw: '提现/支取',
  transfer: '转账',
  consumption: '消费',
  refund: '退款',
  reversal: '冲正',
  wealth_purchase: '理财申购',
  wealth_redeem: '理财赎回',
  loan_disbursement: '贷款放款',
  loan_repayment: '贷款还款',
}

const TXN_STATUS_LABELS = {
  success: '成功',
  failed: '失败',
  pending: '处理中',
  reversed: '已冲正',
}

const chatEndpoint = computed(() => '/api/chat')

const QUICK_ACTIONS = [
  '查询账户余额',
  '查询近期交易明细',
  '申请账户冻结/挂失',
  '转账限额和手续费怎么算',
  '转人工客服',
]

const INFLOW_TYPES = new Set(['deposit', 'refund', 'loan_disbursement', 'wealth_redeem'])

function isInflow(txn) {
  return INFLOW_TYPES.has(txn?.transaction_type)
}

function maskAccountNo(accountNo) {
  const value = String(accountNo ?? '')
  if (value.length <= 8) {
    return value
  }
  return `${value.slice(0, 3)} **** **** ${value.slice(-4)}`
}

function formatDateTime(value) {
  if (!value) {
    return ''
  }
  return String(value).replace('T', ' ').slice(0, 16)
}

async function sendQuickAction(text) {
  if (isSending.value) {
    return
  }
  draftMessage.value = text
  await sendTextMessage()
}
const chatHistoryEndpoint = computed(
  () => `/api/chat/history?sender_id=${encodeURIComponent(senderId.value.trim())}`
)
const bankAccountsEndpoint = computed(
  () => `/bank/api/v1/customers/${encodeURIComponent(senderId.value.trim())}/accounts`
)
function bankTransactionsEndpoint(accountNo) {
  return `/bank/api/v1/accounts/${encodeURIComponent(accountNo)}/transactions?page_size=10`
}

function createBaseMessage(role) {
  return {
    id: crypto.randomUUID(),
    role,
    buttons: [],
  }
}

function appendUserText(text) {
  messages.value.push({
    ...createBaseMessage('user'),
    type: 'text',
    text,
  })
}

function appendUserObject(objectType, payload) {
  messages.value.push({
    ...createBaseMessage('user'),
    type: 'object',
    objectType,
    payload,
  })
}

function appendBotMessages(botMessages) {
  for (const message of botMessages) {
    appendMessage('bot', message)
  }
}

function appendMessage(role, message) {
  if (role === 'divider') {
    messages.value.push({
      ...createBaseMessage('divider'),
      type: 'divider',
      text: message.text ?? '以上为历史消息',
    })
    return
  }

  if (message.object) {
    messages.value.push({
      ...createBaseMessage(role),
      type: 'object',
      objectType: message.object.type,
      payload: message.object,
    })
  } else {
    messages.value.push({
      ...createBaseMessage(role),
      type: 'text',
      text: message.text ?? '',
    })
  }
}

function setHistoryMessages(historyMessages) {
  messages.value = []
  for (const message of historyMessages) {
    const role = ['user', 'bot', 'divider'].includes(message.role) ? message.role : 'bot'
    appendMessage(role, message)
  }
}

async function scrollToBottom() {
  await nextTick()
  const container = messagesContainer.value
  if (!container) {
    return
  }
  container.scrollTop = container.scrollHeight
}

watch(
  () => messages.value.length,
  async () => {
    await scrollToBottom()
  }
)

function resetConversation() {
  messages.value = []
  errorMessage.value = ''
}

function formatAmount(amount) {
  const numericAmount = Number(amount)
  if (Number.isNaN(numericAmount)) {
    return '￥0.00'
  }
  return `￥${numericAmount.toFixed(2)}`
}

function formatAccountSummary(account) {
  const productName = account.account_product?.product_name
  return productName ? `账户产品：${productName}` : '银行账户'
}

function formatTransactionSummary(txn) {
  const typeLabel = TXN_TYPE_LABELS[txn.transaction_type] ?? txn.transaction_type ?? '交易'
  const statusLabel = TXN_STATUS_LABELS[txn.transaction_status] ?? txn.transaction_status ?? '未知'
  return `${typeLabel} · ${statusLabel}`
}

function getObjectTitle(message) {
  const payload = message.payload ?? {}
  if (payload.title) {
    return payload.title
  }
  return message.objectType === 'account' ? '银行账户' : '交易记录'
}

function getObjectIdentifier(message) {
  const payload = message.payload ?? {}
  const id = payload.account_no ?? payload.transaction_no ?? payload.id
  const label = message.objectType === 'account' ? '账户号' : '交易号'
  return id ? `${label}：${id}` : label
}

function getObjectSummary(message) {
  const payload = message.payload ?? {}
  if (message.objectType === 'account') {
    const productName = payload.account_product?.product_name ?? payload.attributes?.product_code
    return productName ? `账户产品：${productName}` : '银行账户'
  }
  return formatTransactionSummary(payload.attributes ?? payload)
}

function getObjectAmount(message) {
  const payload = message.payload ?? {}
  const amount = message.objectType === 'account'
    ? payload.balance_amount ?? payload.attributes?.balance_amount
    : payload.transaction_amount ?? payload.attributes?.transaction_amount
  return formatAmount(amount)
}

async function fetchSidebarData() {
  const currentSenderId = senderId.value.trim()
  accounts.value = []
  transactions.value = []
  sidebarError.value = ''

  if (!currentSenderId) {
    return
  }

  isLoadingSidebar.value = true
  try {
    const accountsResponse = await fetch(bankAccountsEndpoint.value, {
      headers: BANK_HEADERS,
    })
    const accountsPayload = await accountsResponse.json()

    if (!accountsResponse.ok) {
      throw new Error(accountsPayload.message || accountsPayload.detail || '加载账户列表失败。')
    }

    const accountList = Array.isArray(accountsPayload?.data?.list) ? accountsPayload.data.list : []
    accounts.value = accountList

    if (accountList.length > 0) {
      const firstAccountNo = accountList[0].account_no
      const txnsResponse = await fetch(bankTransactionsEndpoint(firstAccountNo), {
        headers: BANK_HEADERS,
      })
      const txnsPayload = await txnsResponse.json()
      if (!txnsResponse.ok) {
        throw new Error(txnsPayload.message || txnsPayload.detail || '加载交易列表失败。')
      }
      transactions.value = Array.isArray(txnsPayload?.data?.list) ? txnsPayload.data.list : []
    }
  } catch (error) {
    sidebarError.value = error instanceof Error ? error.message : '加载右侧列表失败。'
  } finally {
    isLoadingSidebar.value = false
  }
}

async function fetchChatHistory() {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    messages.value = []
    return
  }

  try {
    const response = await fetch(chatHistoryEndpoint.value)
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '加载历史消息失败。')
    }
    if (currentSenderId === senderId.value.trim()) {
      setHistoryMessages(Array.isArray(data?.messages) ? data.messages : [])
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载历史消息失败。'
  }
}

async function sendPayload(payload) {
  if (isSending.value) {
    return
  }

  errorMessage.value = ''
  isSending.value = true

  try {
    const response = await fetch(chatEndpoint.value, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        sender_id: senderId.value.trim(),
        ...payload,
      }),
    })

    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '请求失败。')
    }

    appendBotMessages(data.messages ?? [])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败。'
  } finally {
    isSending.value = false
  }
}

async function sendTextMessage() {
  const text = draftMessage.value.trim()
  const currentSenderId = senderId.value.trim()

  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }
  if (!text) {
    return
  }

  draftMessage.value = ''
  appendUserText(text)
  await sendPayload({ text })
}

async function sendAccount(account) {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }

  const title = account.account_product?.product_name || '银行账户'
  appendUserObject('account', account)
  await sendPayload({
    object: {
      type: 'account',
      id: account.account_no,
      title,
      attributes: {
        balance_amount: account.balance_amount,
        currency_code: account.currency_code,
        product_code: account.account_product?.product_code,
      },
    },
  })
}

async function sendTransaction(txn) {
  const currentSenderId = senderId.value.trim()
  if (!currentSenderId) {
    errorMessage.value = '请先输入 sender_id。'
    return
  }

  const typeLabel = TXN_TYPE_LABELS[txn.transaction_type] ?? txn.transaction_type ?? '账户交易'
  appendUserObject('transaction', txn)
  await sendPayload({
    object: {
      type: 'transaction',
      id: txn.transaction_no,
      title: `${typeLabel}交易`,
      attributes: {
        transaction_type: txn.transaction_type,
        transaction_status: txn.transaction_status,
        transaction_amount: txn.transaction_amount,
        currency_code: txn.currency_code,
        transaction_at: txn.transaction_at,
      },
    },
  })
}

watch(
  () => senderId.value.trim(),
  async (value, previousValue) => {
    if (value === previousValue) {
      return
    }

    resetConversation()
    if (!value) {
      accounts.value = []
      transactions.value = []
      return
    }
    await Promise.all([fetchSidebarData(), fetchChatHistory()])
  }
)

onMounted(async () => {
  await Promise.all([fetchSidebarData(), fetchChatHistory()])
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 10 12 4l9 6" />
            <path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8" />
            <path d="M3 20h18" />
          </svg>
        </div>
        <div class="brand-text">
          <div class="brand-name">智能银行客服助手</div>
          <div class="brand-sub">Smart Banking Assistant · 账户与交易服务</div>
        </div>
      </div>

      <div class="topbar-right">
        <span class="status-pill">
          <span class="status-dot"></span>
          在线服务中
        </span>
        <span class="secure-pill">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3 5 6v6c0 4.2 3 7.6 7 9 4-1.4 7-4.8 7-9V6l-7-3Z" />
            <path d="m9 12 2 2 4-4" />
          </svg>
          安全加密通道
        </span>
      </div>
    </header>

    <div class="workspace">
      <div class="chat-card">
        <section class="controls">
          <label class="field">
            <span class="field-label">客户号 sender_id</span>
            <div class="field-row">
              <input v-model="senderId" type="text" placeholder="CUS00000001" />
              <button
                type="button"
                class="secondary-button"
                :disabled="isLoadingSidebar"
                @click="fetchSidebarData"
              >
                {{ isLoadingSidebar ? '加载中...' : '刷新账户数据' }}
              </button>
            </div>
          </label>
        </section>

        <section ref="messagesContainer" class="messages">
          <div v-if="messages.length === 0" class="empty-state">
            <div class="empty-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
                <path d="M8.5 11h.01M12 11h.01M15.5 11h.01" />
              </svg>
            </div>
            <h3>您好，欢迎使用智能银行客服</h3>
            <p>
              我可以帮您查询账户状态与余额、查看交易明细、受理账户冻结/挂失申请，
              也可以解答转账限额、开户规则等银行业务问题。
            </p>
            <p class="empty-hint">点击下方快捷问题，或从右侧选择账户 / 交易发送给客服。</p>
          </div>

          <article
            v-for="message in messages"
            :key="message.id"
            class="message"
            :class="message.role"
          >
            <template v-if="message.type === 'divider'">
              <div class="history-divider">
                <span>{{ message.text }}</span>
              </div>
            </template>

            <template v-else>
              <div class="avatar" :class="message.role">
                {{ message.role === 'user' ? '我' : '银' }}
              </div>

              <div class="message-body">
                <div class="meta">
                  {{ message.role === 'user' ? '我' : '智能银行客服' }}
                </div>

                <div class="bubble">
                  <template v-if="message.type === 'object'">
                    <div class="object-card" :class="`object-card-${message.objectType}`">
                      <div class="object-card-badge">
                        {{ message.objectType === 'account' ? '银行账户' : '交易记录' }}
                      </div>
                      <div class="object-card-title">{{ getObjectTitle(message) }}</div>
                      <div class="object-card-meta">{{ getObjectIdentifier(message) }}</div>
                      <div class="object-card-meta">{{ getObjectSummary(message) }}</div>
                      <div class="object-card-price">{{ getObjectAmount(message) }}</div>
                    </div>
                  </template>

                  <template v-else>
                    <p>{{ message.text }}</p>
                  </template>
                </div>
              </div>
            </template>
          </article>

          <article v-if="isSending" class="message bot typing-row">
            <div class="avatar bot">银</div>
            <div class="message-body">
              <div class="meta">智能银行客服</div>
              <div class="bubble typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          </article>
        </section>

        <p v-if="errorMessage" class="error-message">
          {{ errorMessage }}
        </p>

        <div class="quick-actions">
          <button
            v-for="action in QUICK_ACTIONS"
            :key="action"
            type="button"
            class="chip"
            :disabled="isSending"
            @click="sendQuickAction(action)"
          >
            {{ action }}
          </button>
        </div>

        <form class="composer" @submit.prevent="sendTextMessage">
          <input
            v-model="draftMessage"
            type="text"
            placeholder="请输入您要咨询的银行业务，例如：查询账户 ACC0000000001 的余额"
            :disabled="isSending"
          />
          <button type="submit" :disabled="isSending || !draftMessage.trim()">
            {{ isSending ? '发送中...' : '发送' }}
          </button>
        </form>
      </div>

      <aside class="sidebar">
        <div class="sidebar-header">
          <h2>我的业务</h2>
          <p>选择账户或交易，一键发送给客服咨询</p>
        </div>

        <div class="tabs">
          <button
            type="button"
            class="tab-button"
            :class="{ active: activeTab === 'accounts' }"
            @click="activeTab = 'accounts'"
          >
            银行账户
            <span class="tab-count">{{ accounts.length }}</span>
          </button>
          <button
            type="button"
            class="tab-button"
            :class="{ active: activeTab === 'transactions' }"
            @click="activeTab = 'transactions'"
          >
            交易明细
            <span class="tab-count">{{ transactions.length }}</span>
          </button>
        </div>

        <p v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</p>

        <div v-if="activeTab === 'accounts'" class="sidebar-list">
          <div v-if="isLoadingSidebar" class="sidebar-empty">正在加载账户数据...</div>
          <div v-else-if="!accounts.length" class="sidebar-empty">
            暂无账户数据（请输入有效的客户号）
          </div>

          <article v-for="account in accounts" :key="account.account_no" class="bank-card">
            <div class="bank-card-top">
              <span class="bank-card-name">{{ account.account_product?.product_name || '银行账户' }}</span>
              <span class="bank-card-chip" aria-hidden="true"></span>
            </div>
            <div class="bank-card-no">{{ maskAccountNo(account.account_no) }}</div>
            <div class="bank-card-bottom">
              <div>
                <div class="bank-card-label">可用余额 · {{ account.currency_code }}</div>
                <div class="bank-card-amount">{{ formatAmount(account.balance_amount) }}</div>
              </div>
              <button
                type="button"
                class="card-send-button"
                :disabled="isSending"
                @click="sendAccount(account)"
              >
                发送账户
              </button>
            </div>
          </article>
        </div>

        <div v-else class="sidebar-list">
          <div v-if="isLoadingSidebar" class="sidebar-empty">正在加载交易记录...</div>
          <div v-else-if="!transactions.length" class="sidebar-empty">暂无交易记录</div>

          <article v-for="txn in transactions" :key="txn.transaction_no" class="txn-item">
            <div class="txn-icon" :class="isInflow(txn) ? 'in' : 'out'">
              {{ isInflow(txn) ? '入' : '出' }}
            </div>
            <div class="txn-main">
              <div class="txn-row">
                <span class="txn-title">{{ TXN_TYPE_LABELS[txn.transaction_type] ?? txn.transaction_type }}</span>
                <span class="txn-amount" :class="isInflow(txn) ? 'in' : 'out'">
                  {{ isInflow(txn) ? '+' : '-' }}{{ formatAmount(txn.transaction_amount) }}
                </span>
              </div>
              <div class="txn-row txn-sub">
                <span>{{ formatDateTime(txn.transaction_at) }}</span>
                <span class="txn-status" :class="txn.transaction_status">
                  {{ TXN_STATUS_LABELS[txn.transaction_status] ?? txn.transaction_status }}
                </span>
              </div>
              <div class="txn-row txn-sub">
                <span class="txn-no">{{ txn.transaction_no }}</span>
                <button
                  type="button"
                  class="link-button"
                  :disabled="isSending"
                  @click="sendTransaction(txn)"
                >
                  发送交易 →
                </button>
              </div>
            </div>
          </article>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  background: #eef2f7;
  color: #0f1e36;
}

:global(button),
:global(input) {
  font: inherit;
}

.app-shell {
  --navy-900: #0a1f44;
  --navy-800: #0f2a5c;
  --navy-700: #163a7a;
  --navy-600: #1e4a9a;
  --gold-500: #c9a24a;
  --gold-400: #dcb866;
  --gold-100: #f8f0dc;
  --ink: #0f1e36;
  --muted: #64748b;
  --line: rgba(15, 42, 92, 0.1);
  --surface: #ffffff;
  --success: #0f9d6b;
  --danger: #d0453f;

  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(1200px 400px at 0% 0%, rgba(30, 74, 154, 0.12), transparent 60%),
    radial-gradient(900px 400px at 100% 100%, rgba(201, 162, 74, 0.12), transparent 60%),
    #eef2f7;
}

/* ===== 顶部导航 ===== */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 28px;
  background: linear-gradient(90deg, var(--navy-900), var(--navy-700));
  color: #fff;
  box-shadow: 0 6px 24px rgba(10, 31, 68, 0.25);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: var(--navy-900);
  background: linear-gradient(135deg, var(--gold-400), var(--gold-500));
  box-shadow: 0 6px 16px rgba(201, 162, 74, 0.4);
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.brand-sub {
  margin-top: 2px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.65);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-pill,
.secure-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.08);
}

.secure-pill {
  color: var(--gold-400);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.25);
}

/* ===== 主体布局 ===== */
.workspace {
  flex: 1;
  width: min(1680px, 100%);
  margin: 0 auto;
  padding: 20px 24px 24px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 20px;
}

.chat-card,
.sidebar {
  height: calc(100vh - 68px - 44px);
  min-height: 560px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 18px 50px rgba(15, 42, 92, 0.08);
  display: flex;
  flex-direction: column;
}

/* ===== 客户号栏 ===== */
.controls {
  padding: 16px 22px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #f8fafd, #ffffff);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--navy-700);
}

.field-row {
  display: flex;
  gap: 10px;
}

.field input,
.composer input {
  width: 100%;
  min-width: 0;
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid rgba(15, 42, 92, 0.16);
  border-radius: 12px;
  background: #fff;
  color: var(--ink);
  font-size: 14px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.field input:focus,
.composer input:focus {
  outline: none;
  border-color: var(--navy-600);
  box-shadow: 0 0 0 3px rgba(30, 74, 154, 0.12);
}

/* ===== 消息区 ===== */
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background:
    linear-gradient(180deg, rgba(248, 250, 253, 0.6), rgba(255, 255, 255, 0.9));
}

.empty-state {
  margin: auto;
  max-width: 460px;
  text-align: center;
  color: var(--muted);
  line-height: 1.75;
}

.empty-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 14px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  color: var(--navy-700);
  background: linear-gradient(135deg, #e8eefb, var(--gold-100));
}

.empty-state h3 {
  margin: 0 0 8px;
  font-size: 18px;
  color: var(--ink);
}

.empty-state p {
  margin: 0 0 6px;
  font-size: 14px;
}

.empty-hint {
  color: var(--gold-500);
  font-weight: 600;
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: min(78%, 760px);
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message.bot {
  align-self: flex-start;
}

.message.divider {
  align-self: stretch;
  max-width: none;
}

.message-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.message.user .message-body {
  align-items: flex-end;
}

.avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
}

.avatar.bot {
  color: var(--navy-900);
  background: linear-gradient(135deg, var(--gold-400), var(--gold-500));
  box-shadow: 0 4px 10px rgba(201, 162, 74, 0.35);
}

.avatar.user {
  color: #fff;
  background: linear-gradient(135deg, var(--navy-700), var(--navy-600));
}

.meta {
  font-size: 12px;
  color: var(--muted);
}

.bubble {
  padding: 12px 16px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 42, 92, 0.05);
}

.message.bot .bubble {
  border-top-left-radius: 4px;
  border-left: 3px solid var(--gold-500);
}

.message.user .bubble {
  border-top-right-radius: 4px;
  border-color: transparent;
  color: #fff;
  background: linear-gradient(135deg, var(--navy-800), var(--navy-600));
  box-shadow: 0 10px 24px rgba(15, 42, 92, 0.22);
}

.bubble p {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.history-divider {
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--muted);
  font-size: 12px;
}

.history-divider::before,
.history-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--line);
}

.history-divider span {
  padding: 4px 12px;
  border-radius: 999px;
  background: #f1f5fb;
  border: 1px solid var(--line);
}

/* 输入中动画 */
.typing {
  display: inline-flex;
  gap: 5px;
  padding: 14px 18px;
}

.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--navy-600);
  opacity: 0.35;
  animation: blink 1.2s infinite ease-in-out;
}

.typing span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

/* 聊天中的对象卡片 */
.object-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 250px;
}

.object-card-badge {
  width: fit-content;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--navy-900);
  background: var(--gold-400);
}

.object-card-title {
  font-size: 15px;
  font-weight: 600;
}

.object-card-meta {
  font-size: 13px;
  opacity: 0.85;
}

.object-card-price {
  font-size: 18px;
  font-weight: 700;
  color: var(--gold-400);
}

.message.bot .object-card-price {
  color: var(--navy-700);
}

/* ===== 快捷问题与输入框 ===== */
.error-message,
.sidebar-error {
  margin: 0;
  padding: 10px 22px;
  font-size: 13px;
  color: var(--danger);
  background: #fdf1f0;
  border-top: 1px solid rgba(208, 69, 63, 0.15);
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 22px 0;
  border-top: 1px solid var(--line);
}

.chip {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(30, 74, 154, 0.2);
  background: #f3f6fc;
  color: var(--navy-700);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.chip:hover:not(:disabled) {
  background: var(--navy-700);
  border-color: var(--navy-700);
  color: #fff;
}

.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer {
  display: flex;
  gap: 10px;
  padding: 12px 22px 20px;
}

.composer button,
.secondary-button {
  flex-shrink: 0;
  min-height: 44px;
  padding: 0 18px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
}

.composer button {
  min-width: 96px;
  border: none;
  color: var(--navy-900);
  background: linear-gradient(135deg, var(--gold-400), var(--gold-500));
  box-shadow: 0 10px 22px rgba(201, 162, 74, 0.35);
}

.secondary-button {
  border: 1px solid rgba(30, 74, 154, 0.25);
  background: #fff;
  color: var(--navy-700);
}

.composer button:hover:not(:disabled),
.secondary-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.composer button:disabled,
.secondary-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

/* ===== 右侧业务栏 ===== */
.sidebar-header {
  padding: 20px 22px 14px;
  color: #fff;
  background: linear-gradient(135deg, var(--navy-800), var(--navy-600));
}

.sidebar-header h2 {
  margin: 0;
  font-size: 18px;
}

.sidebar-header p {
  margin: 6px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.tabs {
  display: flex;
  gap: 6px;
  margin: 14px 22px 4px;
  padding: 4px;
  border-radius: 12px;
  background: #f1f5fb;
}

.tab-button {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-button.active {
  background: #fff;
  color: var(--navy-800);
  box-shadow: 0 4px 12px rgba(15, 42, 92, 0.1);
}

.tab-count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  background: rgba(15, 42, 92, 0.08);
}

.tab-button.active .tab-count {
  color: var(--navy-900);
  background: var(--gold-400);
}

.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 22px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidebar-empty {
  margin: 40px auto;
  font-size: 13px;
  color: var(--muted);
  text-align: center;
}

/* 银行卡样式 */
.bank-card {
  position: relative;
  padding: 16px 18px;
  border-radius: 16px;
  color: #fff;
  overflow: hidden;
  background:
    radial-gradient(220px 120px at 100% 0%, rgba(220, 184, 102, 0.35), transparent 70%),
    linear-gradient(135deg, var(--navy-900), var(--navy-600));
  box-shadow: 0 12px 26px rgba(15, 42, 92, 0.25);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.bank-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.bank-card-name {
  font-size: 14px;
  font-weight: 600;
}

.bank-card-chip {
  width: 34px;
  height: 24px;
  border-radius: 5px;
  background: linear-gradient(135deg, var(--gold-400), var(--gold-500));
  box-shadow: inset 0 0 0 1px rgba(10, 31, 68, 0.25);
}

.bank-card-no {
  font-family: "Consolas", "SFMono-Regular", monospace;
  font-size: 16px;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.92);
}

.bank-card-bottom {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
}

.bank-card-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.65);
}

.bank-card-amount {
  margin-top: 2px;
  font-size: 20px;
  font-weight: 700;
  color: var(--gold-400);
}

.card-send-button {
  padding: 7px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.card-send-button:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.25);
}

.card-send-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 交易明细列表 */
.txn-item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fff;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.txn-item:hover {
  border-color: rgba(201, 162, 74, 0.5);
  box-shadow: 0 8px 20px rgba(15, 42, 92, 0.08);
}

.txn-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
}

.txn-icon.in {
  color: var(--success);
  background: rgba(15, 157, 107, 0.1);
}

.txn-icon.out {
  color: var(--navy-700);
  background: rgba(30, 74, 154, 0.1);
}

.txn-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.txn-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.txn-title {
  font-size: 14px;
  font-weight: 600;
}

.txn-amount {
  font-size: 15px;
  font-weight: 700;
}

.txn-amount.in {
  color: var(--success);
}

.txn-amount.out {
  color: var(--ink);
}

.txn-sub {
  font-size: 12px;
  color: var(--muted);
}

.txn-no {
  font-family: "Consolas", "SFMono-Regular", monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.txn-status {
  padding: 1px 8px;
  border-radius: 999px;
  background: #f1f5fb;
}

.txn-status.success {
  color: var(--success);
  background: rgba(15, 157, 107, 0.1);
}

.txn-status.failed {
  color: var(--danger);
  background: rgba(208, 69, 63, 0.1);
}

.txn-status.pending {
  color: #b7791f;
  background: rgba(201, 162, 74, 0.15);
}

.link-button {
  flex-shrink: 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--navy-600);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.link-button:hover:not(:disabled) {
  color: var(--gold-500);
}

.link-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 响应式 ===== */
@media (max-width: 1180px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .chat-card {
    height: 78vh;
  }

  .sidebar {
    height: auto;
    min-height: 420px;
  }
}

@media (max-width: 720px) {
  .topbar {
    padding: 12px 16px;
  }

  .topbar-right {
    display: none;
  }

  .workspace {
    padding: 0;
    gap: 0;
  }

  .chat-card,
  .sidebar {
    border-radius: 0;
    border-left: none;
    border-right: none;
  }

  .message {
    max-width: 100%;
  }

  .composer,
  .field-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
