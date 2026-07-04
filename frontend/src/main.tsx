import '@xyflow/react/dist/style.css';
import 'antd/dist/reset.css';
import './styles.css';

import {
  Alert,
  App as AntApp,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Divider,
  Empty,
  Form,
  Input,
  Layout,
  List,
  Modal,
  Segmented,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
  Upload,
  message,
  theme,
} from 'antd';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  DownloadOutlined,
  FileTextOutlined,
  GithubOutlined,
  GoogleOutlined,
  HistoryOutlined,
  LockOutlined,
  MinusOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import dayjs from 'dayjs';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  closeCase,
  downloadCaseReport,
  getCase,
  getSystemStatus,
  getStoredToken,
  listDueReminders,
  listCases,
  login,
  me,
  register,
  setStoredToken,
  sendConversationMessage,
  submitFollowup,
} from './api';
import { buildStateMachineElements, caseStatusLabels } from './stateMachine';
import type { CaseDetail, CaseListItem, CaseResponse, CaseStatus, ChatMessage, Reminder, User } from './types';

const { Header, Content, Sider } = Layout;
const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

const statusColors: Partial<Record<CaseStatus, string>> = {
  NEED_MORE_INFO: 'gold',
  FOLLOWUP_PENDING: 'blue',
  FOLLOWUP_REVIEW: 'purple',
  IMPROVING: 'green',
  WORSENING: 'red',
  ESCALATED: 'volcano',
  CLOSED: 'default',
};

function createDebugUserId() {
  const key = 'tomatoAgentWorkbenchUserId';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const next = `workbench-${crypto.randomUUID()}`;
  sessionStorage.setItem(key, next);
  return next;
}

function responseToMessage(response: CaseResponse) {
  const lines = [response.message];
  if (response.decision?.questions.length) {
    lines.push('', ...response.decision.questions.map((question, index) => `${index + 1}. ${question}`));
  }
  if (response.diagnosis) {
    lines.push(
      '',
      `疑似问题：${response.diagnosis.suspected_problem || '-'} / ${response.diagnosis.likelihood || '-'}`,
    );
  }
  if (response.followup) {
    lines.push(`复查日期：${response.followup.due_date}`);
  }
  if (response.trend) {
    lines.push(`复查趋势：${response.trend}`);
  }
  return lines.join('\n');
}

function formatDate(value?: string | null) {
  if (!value) return '-';
  return dayjs(value).format('YYYY-MM-DD');
}

function statusTag(status?: CaseStatus | null) {
  if (!status) return <Tag>未创建</Tag>;
  return <Tag color={statusColors[status]}>{caseStatusLabels[status] || status}</Tag>;
}

function AgentWorkbench() {
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'agent',
      content:
        '直接描述番茄异常，系统会从对话中自动创建病例，并推进诊断、处置和复查。建议先输入发生部位、症状形态、生长阶段、天气和采收时间。',
    },
  ]);
  const [input, setInput] = useState('');
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [userId, setUserId] = useState(createDebugUserId);
  const [loadingCases, setLoadingCases] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sending, setSending] = useState(false);
  const [filter, setFilter] = useState<string>('active');
  const [followupOpen, setFollowupOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState<string>('checking');
  const [eventLimit, setEventLimit] = useState(8);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewScale, setPreviewScale] = useState(1);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [dueReminders, setDueReminders] = useState<Reminder[]>([]);
  const [remindersOpen, setRemindersOpen] = useState(false);

  const activeStatus = caseDetail?.status || messages.findLast((item) => item.response)?.response?.status;
  const composerStacked = input.split(/\r?\n/).length > 2 || input.length > 48 || imageUrls.length > 0;
  const { nodes, edges } = useMemo(
    () => buildStateMachineElements(activeStatus || null),
    [activeStatus],
  );

  const refreshCases = useCallback(async () => {
    if (!getStoredToken()) {
      setCases([]);
      return;
    }
    setLoadingCases(true);
    try {
      const data = await listCases();
      setCases(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '病例列表加载失败');
    } finally {
      setLoadingCases(false);
    }
  }, []);

  const refreshDetail = useCallback(async (caseId: number | null) => {
    if (!caseId) {
      setCaseDetail(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const detail = await getCase(caseId);
      setCaseDetail(detail);
      setMessages(caseDetailToMessages(detail));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '病例详情加载失败');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    void getSystemStatus()
      .then((result) => setSystemStatus(result.status))
      .catch(() => setSystemStatus('offline'));
  }, []);

  useEffect(() => {
    if (!getStoredToken()) {
      setAuthChecking(false);
      return;
    }
    void me()
      .then((user) => {
        setCurrentUser(user);
        setUserId(String(user.id));
        return Promise.all([refreshCases(), listDueReminders()]);
      })
      .then(([, reminders]) => setDueReminders(reminders))
      .catch(() => {
        setStoredToken(null);
        setCurrentUser(null);
      })
      .finally(() => {
        setAuthChecking(false);
      });
  }, [refreshCases]);

  useEffect(() => {
    void refreshDetail(selectedCaseId);
  }, [refreshDetail, selectedCaseId]);

  const visibleCases = useMemo(() => {
    if (filter === 'all') return cases;
    if (filter === 'closed') return cases.filter((item) => item.status === 'CLOSED');
    return cases.filter((item) => !['CLOSED', 'ESCALATED'].includes(item.status));
  }, [cases, filter]);

  async function handleSend() {
    const text = input.trim();
    if (!text && imageUrls.length === 0) return;
    const content = text || '已上传图片证据，请结合病例上下文判断。';
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      imageUrls,
    };
    setMessages((current) => [...current, userMessage]);
    setInput('');
    setImageUrls([]);
    setSending(true);
    try {
      const result = await sendConversationMessage({
        user_id: userId,
        case_id: selectedCaseId,
        message: content,
        image_urls: imageUrls,
      });
      const agentMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'agent',
        content: responseToMessage(result.response),
        response: result.response,
      };
      setMessages((current) => [...current, agentMessage]);
      setSelectedCaseId(result.case_id);
      await refreshCases();
      await refreshDetail(result.case_id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '发送失败');
    } finally {
      setSending(false);
    }
  }

  function handleNewConversation() {
    sessionStorage.removeItem('tomatoAgentWorkbenchUserId');
    setUserId(createDebugUserId());
    setSelectedCaseId(null);
    setCaseDetail(null);
    setMessages([
      {
        id: crypto.randomUUID(),
        role: 'agent',
        content: '已开始新的测试会话。下一条消息会自动创建新的病例。',
      },
    ]);
    setImageUrls([]);
  }

  async function handleImageSelection(file: File) {
    const encoded = await fileToDataUrl(file);
    setImageUrls((current) => {
      if (current.length >= 4) return current;
      return [...current, encoded];
    });
  }

  function removePendingImage(index: number) {
    setImageUrls((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  function openPreview(url: string) {
    setPreviewImage(url);
    setPreviewScale(1);
  }

  async function handleFollowupSubmit(values: {
    description: string;
    has_new_spots?: boolean;
    spots_expanded?: boolean;
    spread_to_new_parts?: boolean;
    fruit_affected?: boolean;
  }) {
    if (!selectedCaseId) return;
    setSending(true);
    try {
      const result = await submitFollowup(selectedCaseId, values);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'user', content: values.description },
        {
          id: crypto.randomUUID(),
          role: 'agent',
          content: `${result.message}${result.trend ? `\n复查趋势：${result.trend}` : ''}`,
        },
      ]);
      setFollowupOpen(false);
      await refreshCases();
      await refreshDetail(selectedCaseId);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复查提交失败');
    } finally {
      setSending(false);
    }
  }

  async function handleCloseCase(values: { summary?: string }) {
    if (!selectedCaseId) return;
    setSending(true);
    try {
      await closeCase(selectedCaseId, values.summary);
      setCloseOpen(false);
      await refreshCases();
      await refreshDetail(selectedCaseId);
      message.success('病例已结案');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '结案失败');
    } finally {
      setSending(false);
    }
  }

  async function handleDownloadReport() {
    if (!selectedCaseId) return;
    try {
      await downloadCaseReport(selectedCaseId);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '报告导出失败');
    }
  }

  async function handleAuthenticated(user: User) {
    setCurrentUser(user);
    setUserId(String(user.id));
    await refreshCases();
    try {
      setDueReminders(await listDueReminders());
    } catch {
      setDueReminders([]);
    }
  }

  function handleLogout() {
    setStoredToken(null);
    setCurrentUser(null);
    setSelectedCaseId(null);
    setCaseDetail(null);
    setCases([]);
    setDueReminders([]);
    setMessages([
      {
        id: 'welcome',
        role: 'agent',
        content:
          '直接描述番茄异常，系统会从对话中自动创建病例，并推进诊断、处置和复查。建议先输入发生部位、症状形态、生长阶段、天气和采收时间。',
      },
    ]);
  }

  if (authChecking) {
    return <AuthLoadingScreen systemStatus={systemStatus} />;
  }

  if (!currentUser) {
    return (
      <LoginPage
        systemStatus={systemStatus}
        onAuthenticated={(user) => void handleAuthenticated(user)}
      />
    );
  }

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <Space direction="vertical" size={0}>
          <Title level={3}>Tomato Case Agent</Title>
          <Text type="secondary">Conversation → Case → Decision → Guardrails → Tools → Memory → Follow-up</Text>
        </Space>
        <Space>
          <Tag color={systemStatus === 'ok' ? 'green' : systemStatus === 'checking' ? 'blue' : 'red'}>
            API {systemStatus}
          </Tag>
          {currentUser ? (
            <Button
              size="small"
              icon={<UserOutlined />}
              onClick={() => setRemindersOpen(true)}
            >
              {currentUser.username} · 待提醒 {dueReminders.length}
            </Button>
          ) : (
            <Tag color="gold">未登录</Tag>
          )}
          <Button icon={<ReloadOutlined />} disabled={!currentUser} onClick={() => void refreshCases()}>
            刷新
          </Button>
          {currentUser ? <Button onClick={handleLogout}>退出</Button> : null}
          <Button icon={<PlusOutlined />} onClick={handleNewConversation}>
            新会话
          </Button>
        </Space>
      </Header>

      <Layout className="workspace">
        <Sider width={320} theme="light" className="case-sider">
          <Space direction="vertical" size={12} className="full-width">
            <Segmented
              block
              value={filter}
              onChange={(value) => setFilter(String(value))}
              options={[
                { label: '活跃', value: 'active' },
                { label: '已结案', value: 'closed' },
                { label: '全部', value: 'all' },
              ]}
            />
            <Spin spinning={loadingCases}>
              <List
                className="case-list"
                dataSource={visibleCases}
                locale={{ emptyText: <Empty description="暂无病例" /> }}
                renderItem={(item) => (
                  <List.Item
                    className={item.id === selectedCaseId ? 'case-list-item selected' : 'case-list-item'}
                    onClick={() => setSelectedCaseId(item.id)}
                  >
                    <Space direction="vertical" size={4} className="full-width">
                      <Space className="case-line">
                        <Text strong>{item.title}</Text>
                        {statusTag(item.status)}
                      </Space>
                      <Text type="secondary">
                        #{item.id} · {item.suspected_problem || '待判断'} · {formatDate(item.followup_date)}
                      </Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Spin>
          </Space>
        </Sider>

        <Content className="main-content">
          <section className="conversation-panel">
            <div className="conversation-toolbar">
              <Space>
                {statusTag(activeStatus || null)}
                <Text type="secondary">
                  {selectedCaseId ? `Case #${selectedCaseId}` : '尚未创建 Case'}
                </Text>
              </Space>
              <Space>
                <Button
                  icon={<CalendarOutlined />}
                  disabled={!selectedCaseId}
                  onClick={() => setFollowupOpen(true)}
                >
                  提交复查
                </Button>
                <Button
                  icon={<CheckCircleOutlined />}
                  disabled={!selectedCaseId || activeStatus === 'CLOSED'}
                  onClick={() => setCloseOpen(true)}
                >
                  结案
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  disabled={!selectedCaseId}
                  onClick={() => void handleDownloadReport()}
                >
                  报告
                </Button>
              </Space>
            </div>

            <div className="message-stream">
              {messages.map((item) => (
                <div key={item.id} className={`chat-bubble ${item.role}`}>
                  <div className="bubble-role">{item.role === 'user' ? '用户' : 'Agent'}</div>
                  <Paragraph>{item.content}</Paragraph>
                  {item.imageUrls?.length ? <ImageStrip urls={item.imageUrls} onPreview={openPreview} /> : null}
                </div>
              ))}
            </div>

            <div className={`composer ${composerStacked ? 'stacked' : ''}`}>
              <Upload
                className="composer-attach"
                accept="image/*"
                showUploadList={false}
                multiple
                beforeUpload={(file) => {
                  void handleImageSelection(file);
                  return Upload.LIST_IGNORE;
                }}
              >
                <Button className="attach-button" shape="circle" icon={<PictureOutlined />} aria-label="上传图片" />
              </Upload>
              <div className="composer-input">
                {imageUrls.length ? (
                  <PendingImageStrip
                    urls={imageUrls}
                    onPreview={openPreview}
                    onRemove={removePendingImage}
                  />
                ) : null}
                <TextArea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="描述症状、回答追问，或说明复查变化..."
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  onPressEnter={(event) => {
                    if (!event.shiftKey) {
                      event.preventDefault();
                      void handleSend();
                    }
                  }}
                />
              </div>
              <Button
                className="send-button"
                type="primary"
                icon={<SendOutlined />}
                loading={sending}
                onClick={() => void handleSend()}
              >
                发送
              </Button>
            </div>
          </section>
        </Content>

        <Sider width={430} theme="light" className="insight-sider">
          <Spin spinning={loadingDetail}>
            <Space direction="vertical" size={14} className="full-width">
              <Card size="small" title={<PanelTitle icon={<FileTextOutlined />} text="当前病例" />}>
                {caseDetail ? (
                  <Space direction="vertical" size={8} className="full-width">
                    <InfoLine label="疑似问题" value={caseDetail.suspected_problem || '-'} />
                    <InfoLine label="可信度" value={caseDetail.likelihood || '-'} />
                    <InfoLine label="部位" value={caseDetail.affected_parts.join('、') || '-'} />
                    <InfoLine label="阶段" value={caseDetail.growth_stage || '-'} />
                    <InfoLine label="环境" value={caseDetail.environment || '-'} />
                    <InfoLine label="天气" value={caseDetail.recent_weather || '-'} />
                    <InfoLine
                      label="采收"
                      value={caseDetail.days_to_harvest != null ? `${caseDetail.days_to_harvest} 天` : '-'}
                    />
                    <InfoLine label="复查日期" value={formatDate(caseDetail.followup_date)} />
                    <ImageEvidence detail={caseDetail} onPreview={openPreview} />
                    {caseDetail.current_plan?.summary ? (
                      <Alert type="success" showIcon message={caseDetail.current_plan.summary} />
                    ) : null}
                  </Space>
                ) : (
                  <Empty description="发送第一条消息后自动创建病例" />
                )}
              </Card>

              <Card size="small" title={<PanelTitle icon={<HistoryOutlined />} text="状态机观察" />}>
                <div className="state-flow">
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    fitView
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable={false}
                    panOnDrag={false}
                    zoomOnScroll={false}
                    zoomOnPinch={false}
                    zoomOnDoubleClick={false}
                  >
                    <Background gap={14} size={1} />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
              </Card>

              <Card size="small" title={<PanelTitle icon={<ClockCircleOutlined />} text="复查与事件记忆" />}>
                {caseDetail ? (
                  <Space direction="vertical" className="full-width" size={12}>
                    <FollowupSummary detail={caseDetail} />
                    <Divider className="tight-divider" />
                    <EventTimeline detail={caseDetail} limit={eventLimit} />
                    {caseDetail.events.length > eventLimit ? (
                      <Button block onClick={() => setEventLimit((current) => current + 8)}>
                        查看更多事件
                      </Button>
                    ) : null}
                  </Space>
                ) : (
                  <Empty description="暂无事件" />
                )}
              </Card>
            </Space>
          </Spin>
        </Sider>
      </Layout>

      <FollowupModal
        open={followupOpen}
        loading={sending}
        onCancel={() => setFollowupOpen(false)}
        onSubmit={(values) => void handleFollowupSubmit(values)}
      />
      <CloseCaseModal
        open={closeOpen}
        loading={sending}
        onCancel={() => setCloseOpen(false)}
        onSubmit={(values) => void handleCloseCase(values)}
      />
      <ImagePreview
        imageUrl={previewImage}
        scale={previewScale}
        onScaleChange={setPreviewScale}
        onClose={() => setPreviewImage(null)}
      />
      <ReminderModal
        open={remindersOpen}
        reminders={dueReminders}
        onCancel={() => setRemindersOpen(false)}
      />
    </Layout>
  );
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function AuthLoadingScreen({ systemStatus }: { systemStatus: string }) {
  return (
    <div className="login-shell">
      <Spin size="large" />
      <Text type="secondary">正在连接 Tomato Case Agent · API {systemStatus}</Text>
    </div>
  );
}

function LoginPage({
  systemStatus,
  onAuthenticated,
}: {
  systemStatus: string;
  onAuthenticated: (user: User) => void;
}) {
  const [form] = Form.useForm();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [loading, setLoading] = useState(false);

  async function submit(values: { username: string; password: string }) {
    setLoading(true);
    try {
      const result = mode === 'login' ? await login(values) : await register(values);
      setStoredToken(result.access_token);
      message.success(mode === 'login' ? '登录成功' : '注册成功');
      onAuthenticated(result.user);
      form.resetFields();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '认证失败');
    } finally {
      setLoading(false);
    }
  }

  function handleSocialLogin(provider: 'Google' | 'GitHub') {
    message.info(`${provider} 登录需要先配置 OAuth Client ID、Client Secret 和回调地址。`);
  }

  return (
    <main className="login-page">
      <div className="login-backdrop" />
      <div className="login-ambient ambient-one" />
      <div className="login-ambient ambient-two" />

      <section className="login-story">
        <div className="brand-mark">
          <span className="brand-symbol">T</span>
          <div>
            <Title level={2}>Tomato Case Agent</Title>
            <Text>番茄病虫害处置闭环管理系统</Text>
          </div>
        </div>

        <div className="hero-copy">
          <Tag color="green">Agentic crop care</Tag>
          <Title>把一次咨询，推进成可复查的处置闭环</Title>
          <Text>
            图片、天气、病例状态和复查提醒会进入同一条事件记忆，Agent 只在安全约束内推进下一步。
          </Text>
        </div>

        <div className="floating-insights">
          <div className="insight-card primary">
            <Text type="secondary">当前链路</Text>
            <strong>Conversation → Case → Tool → Follow-up</strong>
          </div>
          <div className="insight-card pulse">
            <Badge status={systemStatus === 'ok' ? 'success' : 'warning'} />
            <span>API {systemStatus}</span>
          </div>
          <div className="insight-card">
            <Text type="secondary">工具观察</Text>
            <strong>图片识别 · 天气信号 · 复查提醒</strong>
          </div>
        </div>
      </section>

      <section className="login-form-wrap">
        <div className="login-card">
          <Space direction="vertical" size={20} className="full-width">
            <Space direction="vertical" size={4}>
              <Tag icon={<SafetyCertificateOutlined />} color="green">
                受保护的病例工作台
              </Tag>
              <Title level={3}>{mode === 'login' ? '登录账号' : '创建账号'}</Title>
              <Text type="secondary">登录后只会看到属于你的病例、复查和提醒。</Text>
            </Space>

            {systemStatus === 'offline' ? (
              <Alert
                type="warning"
                showIcon
                message="后端服务未连接"
                description="请先启动 FastAPI 后端，或检查 VITE_API_BASE_URL / Vite 代理配置。"
              />
            ) : null}

            <Space className="social-login-row" size={10}>
              <Button block icon={<GoogleOutlined />} onClick={() => handleSocialLogin('Google')}>
                Google
              </Button>
              <Button block icon={<GithubOutlined />} onClick={() => handleSocialLogin('GitHub')}>
                GitHub
              </Button>
            </Space>

            <Divider plain>或使用账号密码</Divider>

            <Segmented
              block
              value={mode}
              onChange={(value) => setMode(value as 'login' | 'register')}
              options={[
                { label: '登录', value: 'login' },
                { label: '注册', value: 'register' },
              ]}
            />

            <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
              <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input
                  size="large"
                  prefix={<UserOutlined />}
                  autoComplete="username"
                  placeholder="例如 xiaxin"
                />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password
                  size="large"
                  prefix={<LockOutlined />}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  placeholder="请输入密码"
                />
              </Form.Item>
              <Button
                block
                size="large"
                type="primary"
                htmlType="submit"
                loading={loading}
                disabled={systemStatus === 'offline'}
              >
                {mode === 'login' ? '进入工作台' : '创建并进入'}
              </Button>
            </Form>
          </Space>
        </div>
      </section>
    </main>
  );
}

function caseDetailToMessages(detail: CaseDetail): ChatMessage[] {
  const events = detail.events;
  const messagesFromEvents = events.flatMap((event, index): ChatMessage[] => {
    if (event.event_type === 'USER_MESSAGE') {
      const imageUrls = Array.isArray(event.structured_data.image_urls)
        ? (event.structured_data.image_urls as string[])
        : [];
      return [
        {
          id: `event-${event.id}`,
          role: 'user',
          content: event.user_input || '',
          imageUrls,
        },
      ];
    }

    if (event.event_type === 'FOLLOWUP_SUBMITTED') {
      return [
        {
          id: `event-${event.id}`,
          role: 'user',
          content: event.user_input || '',
        },
      ];
    }

    if (event.event_type === 'AGENT_RESPONSE') {
      return [
        {
          id: `event-${event.id}`,
          role: 'agent',
          content: responseToMessage(event.system_output as unknown as CaseResponse),
          response: event.system_output as unknown as CaseResponse,
        },
      ];
    }

    if (event.event_type === 'QUESTIONS_ASKED') {
      const questions = Array.isArray(event.system_output.questions)
        ? (event.system_output.questions as string[])
        : [];
      return [
        {
          id: `event-${event.id}`,
          role: 'agent',
          content: ['为了避免误判，请先补充几个关键信息。', ...questions.map((item, i) => `${i + 1}. ${item}`)].join(
            '\n',
          ),
        },
      ];
    }

    if (event.event_type === 'FOLLOWUP_COMPARED') {
      return [
        {
          id: `event-${event.id}`,
          role: 'agent',
          content: `已完成复查比较。趋势：${String(event.system_output.trend || '-')}`,
        },
      ];
    }

    if (
      event.event_type === 'STATE_CHANGED' &&
      !events.slice(index + 1).some((later) => later.event_type === 'AGENT_RESPONSE')
    ) {
      const status = String(event.system_output.status || '');
      if (status === 'FOLLOWUP_PENDING') {
        return [
          {
            id: `event-${event.id}`,
            role: 'agent',
            content: legacyPlanMessage(detail),
          },
        ];
      }
      if (status === 'ESCALATED') {
        return [
          {
            id: `event-${event.id}`,
            role: 'agent',
            content: '当前情况不适合继续仅凭通用建议处理，建议联系当地农技人员或专业人员确认。',
          },
        ];
      }
      if (status === 'CLOSED') {
        return [
          {
            id: `event-${event.id}`,
            role: 'agent',
            content: '病例已结案。',
          },
        ];
      }
    }

    return [];
  });

  if (messagesFromEvents.length) return messagesFromEvents;
  return [
    {
      id: `case-${detail.id}-summary`,
      role: 'agent',
      content: '这个病例来自旧版本事件记录，暂无可回放的完整对话。请查看右侧事件时间线。',
    },
  ];
}

function legacyPlanMessage(detail: CaseDetail) {
  const lines = ['已形成保守的初步判断，并创建复查计划。'];
  if (detail.suspected_problem || detail.likelihood) {
    lines.push('', `疑似问题：${detail.suspected_problem || '-'} / ${detail.likelihood || '-'}`);
  }
  if (detail.followup_date) {
    lines.push(`复查日期：${formatDate(detail.followup_date)}`);
  }
  return lines.join('\n');
}

function PanelTitle({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <Space>
      {icon}
      <span>{text}</span>
    </Space>
  );
}

function InfoLine({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="info-line">
      <Text type="secondary">{label}</Text>
      <Text>{value}</Text>
    </div>
  );
}

function ImageStrip({ urls, onPreview }: { urls: string[]; onPreview: (url: string) => void }) {
  return (
    <div className="image-strip">
      {urls.map((url, index) => (
        <button
          key={`${url.slice(0, 48)}-${index}`}
          className="image-thumb"
          type="button"
          onClick={() => onPreview(url)}
          aria-label={`查看图片 ${index + 1}`}
        >
          <img src={url} alt={`病例图片证据 ${index + 1}`} />
        </button>
      ))}
    </div>
  );
}

function PendingImageStrip({
  urls,
  onPreview,
  onRemove,
}: {
  urls: string[];
  onPreview: (url: string) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="pending-image-strip">
      {urls.map((url, index) => (
        <div className="pending-image" key={`${url.slice(0, 48)}-${index}`}>
          <button className="image-thumb" type="button" onClick={() => onPreview(url)}>
            <img src={url} alt={`待发送图片 ${index + 1}`} />
          </button>
          <Button
            className="remove-image"
            size="small"
            shape="circle"
            icon={<CloseOutlined />}
            onClick={() => onRemove(index)}
            aria-label={`删除图片 ${index + 1}`}
          />
        </div>
      ))}
    </div>
  );
}

function ImageEvidence({ detail, onPreview }: { detail: CaseDetail; onPreview: (url: string) => void }) {
  const imageEvidence = Array.isArray(detail.structured_data.image_evidence)
    ? (detail.structured_data.image_evidence as string[])
    : [];
  if (!imageEvidence.length) return null;
  return (
    <Alert
      type="info"
      showIcon
      message="图片证据已保存"
      description={
        <Space direction="vertical" size={8} className="full-width">
          <Text type="secondary">MVP 阶段尚未执行视觉识别，图片只作为 Case Event 和后续多模态工具的证据。</Text>
          <ImageStrip urls={imageEvidence} onPreview={onPreview} />
        </Space>
      }
    />
  );
}

function ImagePreview({
  imageUrl,
  scale,
  onScaleChange,
  onClose,
}: {
  imageUrl: string | null;
  scale: number;
  onScaleChange: (scale: number) => void;
  onClose: () => void;
}) {
  if (!imageUrl) return null;

  function zoom(delta: number) {
    onScaleChange(Math.min(4, Math.max(0.4, Number((scale + delta).toFixed(2)))));
  }

  return (
    <div
      className="image-preview-overlay"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      onWheel={(event) => {
        event.preventDefault();
        zoom(event.deltaY > 0 ? -0.12 : 0.12);
      }}
    >
      <div className="image-preview-toolbar" onClick={(event) => event.stopPropagation()}>
        <Button shape="circle" icon={<PlusOutlined />} onClick={() => zoom(0.2)} aria-label="放大" />
        <Button shape="circle" icon={<MinusOutlined />} onClick={() => zoom(-0.2)} aria-label="缩小" />
        <Button shape="circle" icon={<CloseOutlined />} onClick={onClose} aria-label="退出" />
      </div>
      <img
        className="image-preview"
        src={imageUrl}
        alt="放大查看"
        style={{ transform: `scale(${scale})` }}
        onClick={(event) => event.stopPropagation()}
      />
    </div>
  );
}

function ReminderModal({
  open,
  reminders,
  onCancel,
}: {
  open: boolean;
  reminders: Reminder[];
  onCancel: () => void;
}) {
  return (
    <Modal title="待处理提醒" open={open} footer={null} onCancel={onCancel}>
      <List
        dataSource={reminders}
        locale={{ emptyText: <Empty description="暂无到期提醒" /> }}
        renderItem={(item) => (
          <List.Item>
            <Space direction="vertical" size={4} className="full-width">
              <Space>
                <Tag color={item.status === 'pending' ? 'blue' : 'default'}>{item.status}</Tag>
                <Text strong>Case #{item.case_id}</Text>
                <Text type="secondary">{dayjs(item.due_at).format('YYYY-MM-DD HH:mm')}</Text>
              </Space>
              <Text type="secondary">{item.reason || '系统提醒复查番茄异常处置效果'}</Text>
            </Space>
          </List.Item>
        )}
      />
    </Modal>
  );
}

function FollowupSummary({ detail }: { detail: CaseDetail }) {
  const active = detail.followups.find((item) => item.status === 'PENDING') || detail.followups.at(-1);
  if (!active) return <Text type="secondary">尚未创建复查任务</Text>;
  return (
    <Space direction="vertical" size={6} className="full-width">
      <Space>
        <Badge status={active.status === 'PENDING' ? 'processing' : 'default'} />
        <Text strong>{formatDate(active.due_date)}</Text>
        <Tag>{active.status}</Tag>
      </Space>
      <div className="checklist">
        {active.checklist.map((item, index) => (
          <Tag key={`${String(item)}-${index}`}>{String(item)}</Tag>
        ))}
      </div>
    </Space>
  );
}

function EventTimeline({ detail, limit }: { detail: CaseDetail; limit: number }) {
  const items = detail.events.slice(-limit).reverse().map((event) => ({
    color: event.event_type === 'STATE_CHANGED' ? 'green' : 'blue',
    children: (
      <Space direction="vertical" size={2}>
        <Space>
          <Text strong>{event.event_type}</Text>
          <Text type="secondary">{dayjs(event.created_at).format('MM-DD HH:mm')}</Text>
        </Space>
        {event.user_input ? <Text type="secondary">{event.user_input}</Text> : null}
      </Space>
    ),
  }));
  return <Timeline items={items} />;
}

function FollowupModal({
  open,
  loading,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (values: {
    description: string;
    has_new_spots?: boolean;
    spots_expanded?: boolean;
    spread_to_new_parts?: boolean;
    fruit_affected?: boolean;
  }) => void;
}) {
  const [form] = Form.useForm();
  return (
    <Modal
      title="提交复查"
      open={open}
      onCancel={onCancel}
      confirmLoading={loading}
      onOk={() => form.submit()}
      okText="提交"
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          has_new_spots: false,
          spots_expanded: false,
          spread_to_new_parts: false,
          fruit_affected: false,
        }}
        onFinish={(values) => {
          onSubmit(values);
          form.resetFields();
        }}
      >
        <Form.Item name="description" label="复查描述" rules={[{ required: true, message: '请填写复查描述' }]}>
          <TextArea rows={4} placeholder="例如：病斑没有增加，老叶略有干枯，新叶正常。" />
        </Form.Item>
        <Form.Item name="has_new_spots" label="是否出现新病斑">
          <Segmented options={[{ label: '否', value: false }, { label: '是', value: true }]} />
        </Form.Item>
        <Form.Item name="spots_expanded" label="原有病斑是否扩大">
          <Segmented options={[{ label: '否', value: false }, { label: '是', value: true }]} />
        </Form.Item>
        <Form.Item name="spread_to_new_parts" label="是否扩展到新部位">
          <Segmented options={[{ label: '否', value: false }, { label: '是', value: true }]} />
        </Form.Item>
        <Form.Item name="fruit_affected" label="果实是否受影响">
          <Segmented options={[{ label: '否', value: false }, { label: '是', value: true }]} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function CloseCaseModal({
  open,
  loading,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (values: { summary?: string }) => void;
}) {
  const [form] = Form.useForm();
  return (
    <Modal
      title="结案确认"
      open={open}
      onCancel={onCancel}
      confirmLoading={loading}
      onOk={() => form.submit()}
      okText="结案"
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="summary" label="结案备注">
          <TextArea rows={3} placeholder="例如：症状稳定，没有新病斑，暂时结案。" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#2f7d4a',
          borderRadius: 8,
          fontFamily:
            'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <AntApp>
        <AgentWorkbench />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
