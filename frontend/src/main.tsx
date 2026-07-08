import '@xyflow/react/dist/style.css';
import 'antd/dist/reset.css';
import './styles.css';

import {
  Alert,
  App as AntApp,
  Badge,
  Button,
  Card,
  Collapse,
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
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  apiUrl,
  downloadCaseReport,
  getCase,
  getSystemStatus,
  getStoredToken,
  listDueReminders,
  listCases,
  login,
  me,
  oauthStartUrl,
  register,
  setStoredToken,
  sendConversationMessage,
} from './api';
import { buildStateMachineElements, caseStatusLabels } from './stateMachine';
import type { AgentTrace, CaseDetail, CaseListItem, CaseResponse, CaseStatus, ChatMessage, Reminder, User } from './types';

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

const agentThinkingSteps = ['观察症状和图片', '判断信息是否足够', '检查采收和用药安全', '生成处理与复查计划'];

function createDebugUserId() {
  const key = 'tomatoAgentWorkbenchUserId';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const next = `workbench-${crypto.randomUUID()}`;
  sessionStorage.setItem(key, next);
  return next;
}

function responseToMessage(response: CaseResponse) {
  if (response.message) return response.message;

  if (response.advice) {
    const advice = response.advice;
    const lines = [humanSummary(response)];

    if (advice.immediate_actions.length) {
      lines.push('', `现在先做这几件事就行：${inlineList(advice.immediate_actions)}。`);
    }
    if (advice.observation_points.length) {
      lines.push(`接下来主要盯住：${inlineList(advice.observation_points)}。`);
    }
    if (advice.chemical_advice || advice.harvest_safety) {
      lines.push('', `${advice.chemical_advice} ${advice.harvest_safety}`.trim());
    }
    if (response.diagnosis?.evidence.length) {
      lines.push('', `我主要是根据 ${inlineList(response.diagnosis.evidence, 4)} 来判断的。`);
    }
    if (response.diagnosis?.confusions.length) {
      lines.push(`不过它也容易和 ${inlineList(response.diagnosis.confusions, 3)} 混在一起，所以先按保守办法处理。`);
    }
    if (advice.escalation_conditions.length) {
      lines.push('', `如果后面出现 ${inlineList(advice.escalation_conditions, 4)}，就别继续自己扛了，建议找当地农技人员确认。`);
    }
    if (advice.followup_timing) {
      lines.push('', `我会按这个病例继续跟踪：${advice.followup_timing}`);
    }
    if (advice.followup_if_better.length || advice.followup_if_worse.length) {
      lines.push(
        `到时候你直接发一句变化就行，比如有没有新增、有没有扩散、果实有没有受影响。我会根据变化重新调整方案。`,
      );
    }
    if (response.decision?.questions.length) {
      lines.push('', '我还需要你补充几句：', ...response.decision.questions.map((question, index) => `${index + 1}. ${question}`));
    }
    return lines.join('\n');
  }

  const lines = [response.message];
  if (response.decision?.questions.length) {
    lines.push('', ...response.decision.questions.map((question, index) => `${index + 1}. ${question}`));
  }
  if (response.diagnosis) {
    lines.push(
      '',
      `疑似问题：${response.diagnosis.suspected_problem || '-'} / ${response.diagnosis.likelihood || '-'}`,
    );
    if (response.diagnosis.evidence.length) {
      lines.push('依据：', ...response.diagnosis.evidence.map((item) => `- ${item}`));
    }
  }
  if (response.followup) {
    lines.push(`下次复查日期：${response.followup.due_date}`);
  }
  if (response.trend) {
    lines.push(`复查趋势：${response.trend}`);
  }
  return lines.join('\n');
}

function inlineList(values?: string[], limit = 5) {
  return (values || []).filter(Boolean).slice(0, limit).join('、') || '几个关键变化';
}

function humanSummary(response: CaseResponse) {
  const advice = response.advice;
  if (!advice) return response.message;
  if (!advice.information_sufficient) {
    return `${advice.plain_summary} 我先不急着给你定病名，因为现在直接处理容易跑偏。`;
  }
  const diagnosis = response.diagnosis?.suspected_problem;
  const category = advice.problem_category ? `${advice.problem_category}类问题` : '番茄异常';
  const severity = advice.severity ? `，严重程度我先按“${advice.severity}”看` : '';
  if (diagnosis) {
    return `我看了一下，更像是 ${diagnosis}，属于${category}${severity}。先别慌，当前更适合按保守办法处理，再用复查结果来验证判断。`;
  }
  return `${advice.plain_summary} 先按“${advice.action_mode}”来处理，我会继续根据你后面发来的变化调整方案。`;
}

function formatDate(value?: string | null) {
  if (!value) return '-';
  return dayjs(value).format('YYYY-MM-DD');
}

function statusTag(status?: CaseStatus | null) {
  if (!status) return <Tag>未创建</Tag>;
  return <Tag color={statusColors[status]}>{caseStatusLabels[status] || status}</Tag>;
}

function geolocationErrorText(error: unknown) {
  const geoError = error as Partial<GeolocationPositionError>;
  if (geoError.code === 1) return '浏览器定位权限被拒绝';
  if (geoError.code === 2) return '浏览器暂时无法获取当前位置';
  if (geoError.code === 3) return '浏览器定位超时';
  return '浏览器定位失败';
}

function AgentWorkbench() {
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [pendingMessagesByCase, setPendingMessagesByCase] = useState<Record<string, ChatMessage[]>>({});
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
  const [systemStatus, setSystemStatus] = useState<string>('checking');
  const [eventLimit, setEventLimit] = useState(8);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewScale, setPreviewScale] = useState(1);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [dueReminders, setDueReminders] = useState<Reminder[]>([]);
  const [remindersOpen, setRemindersOpen] = useState(false);
  const messageStreamRef = useRef<HTMLDivElement | null>(null);
  const selectedCaseIdRef = useRef<number | null>(null);

  useEffect(() => {
    selectedCaseIdRef.current = selectedCaseId;
  }, [selectedCaseId]);

  const activeStatus = caseDetail?.status || messages.findLast((item) => item.response)?.response?.status;
  const composerStacked = input.split(/\r?\n/).length > 2 || input.length > 48 || imageUrls.length > 0;
  const pendingStep = sending ? agentThinkingSteps[messages.length % agentThinkingSteps.length] : agentThinkingSteps[0];
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
    if (!caseId || caseId < 0) {
      setCaseDetail(null);
      if (caseId && caseId < 0) {
        setMessages(pendingMessagesByCase[String(caseId)] || []);
      }
      return;
    }
    setLoadingDetail(true);
    try {
      const detail = await getCase(caseId);
      setCaseDetail(detail);
      setMessages(mergeChatMessages(caseDetailToMessages(detail), pendingMessagesByCase[String(caseId)] || []));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '病例详情加载失败');
    } finally {
      setLoadingDetail(false);
    }
  }, [pendingMessagesByCase]);

  useEffect(() => {
    void getSystemStatus()
      .then((result) => setSystemStatus(result.status))
      .catch(() => setSystemStatus('offline'));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthToken = params.get('access_token');
    if (oauthToken) {
      setStoredToken(oauthToken);
      window.history.replaceState({}, document.title, window.location.pathname);
    }

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

  const scrollMessagesToBottom = useCallback(() => {
    window.requestAnimationFrame(() => {
      const stream = messageStreamRef.current;
      if (stream) stream.scrollTop = stream.scrollHeight;
    });
  }, []);

  useEffect(() => {
    scrollMessagesToBottom();
  }, [messages, scrollMessagesToBottom]);

  const visibleCases = useMemo(() => {
    if (filter === 'all') return cases;
    if (filter === 'closed') return cases.filter((item) => item.status === 'CLOSED');
    return cases.filter((item) => !['CLOSED', 'ESCALATED'].includes(item.status));
  }, [cases, filter]);

  async function handleSend() {
    const text = input.trim();
    if (!text && imageUrls.length === 0) return;
    const content = text || '已上传图片，请分析这次番茄异常。';
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      imageUrls,
    };
    const pendingId = crypto.randomUUID();
    const optimisticCaseId = selectedCaseId ?? -Date.now();
    const pendingMessage: ChatMessage = {
      id: pendingId,
      role: 'agent',
      content: '正在观察症状、检查安全约束，并生成处理和复查计划...',
      pending: true,
    };
    const pendingPair = [userMessage, pendingMessage];
    setMessages((current) => [...current, userMessage, pendingMessage]);
    scrollMessagesToBottom();
    if (!selectedCaseId) {
      const optimisticCase: CaseListItem = {
        id: optimisticCaseId,
        title: content.slice(0, 24) || '新的番茄异常',
        crop: '番茄',
        suspected_problem: 'Agent 正在处理',
        status: 'NEW',
        followup_date: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setCases((current) => [optimisticCase, ...current.filter((item) => item.id !== optimisticCaseId)]);
      setSelectedCaseId(optimisticCaseId);
    }
    const pendingCaseKey = String(selectedCaseId ?? optimisticCaseId);
    setPendingMessagesByCase((current) => ({
      ...current,
      [pendingCaseKey]: mergeChatMessages(current[pendingCaseKey] || [], pendingPair),
    }));
    setInput('');
    setImageUrls([]);
    setSending(true);
    try {
      const location = await getBrowserLocation();
      const requestCaseId = selectedCaseId && selectedCaseId > 0 ? selectedCaseId : undefined;
      const result = await sendConversationMessage({
        user_id: userId,
        case_id: requestCaseId,
        message: content,
        image_urls: imageUrls,
        ...location,
      });
      const shouldStayOnSendingCase =
        selectedCaseIdRef.current === selectedCaseId || selectedCaseIdRef.current === optimisticCaseId;
      setPendingMessagesByCase((current) => {
        const next = { ...current };
        const pendingForCase = current[pendingCaseKey] || pendingPair;
        delete next[pendingCaseKey];
        if (!shouldStayOnSendingCase) {
          next[String(result.case_id)] = pendingForCase;
        }
        return next;
      });
      if (shouldStayOnSendingCase) {
        setSelectedCaseId(result.case_id);
      }
      setCases((current) =>
        current
          .map((item) =>
            item.id === optimisticCaseId
              ? {
                  ...item,
                  id: result.case_id,
                  suspected_problem: result.response.diagnosis?.suspected_problem || item.suspected_problem,
                  status: result.response.status,
                  followup_date: result.response.followup?.due_date || item.followup_date,
                  updated_at: new Date().toISOString(),
                }
              : item,
          )
          .filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index),
      );
      void refreshCases();
      const detail = await getCase(result.case_id);
      if (shouldStayOnSendingCase) {
        setCaseDetail(detail);
        await streamAgentMessage(pendingId, responseToMessage(result.response), result.response);
      } else {
        setPendingMessagesByCase((current) => {
          const next = { ...current };
          delete next[String(result.case_id)];
          return next;
        });
      }
    } catch (error) {
      setPendingMessagesByCase((current) => ({
        ...current,
        [pendingCaseKey]: (current[pendingCaseKey] || pendingPair).map((item) =>
          item.id === pendingId
            ? {
                ...item,
                pending: false,
                content: `这次 Agent 没有完成决策：${error instanceof Error ? error.message : '发送失败'}`,
              }
            : item,
        ),
      }));
      setMessages((current) =>
        current.map((item) =>
          item.id === pendingId
            ? {
                ...item,
                pending: false,
                content: `这次 Agent 没有完成决策：${error instanceof Error ? error.message : '发送失败'}`,
              }
            : item,
        ),
      );
      message.error(error instanceof Error ? error.message : '发送失败');
    } finally {
      setSending(false);
    }
  }

  async function getBrowserLocation(): Promise<{
    latitude?: number | null;
    longitude?: number | null;
    location_label?: string | null;
    location_source?: string | null;
    location_error?: string | null;
  }> {
    if (!navigator.geolocation) {
      return {
        location_label: '用户未提供地点',
        location_source: 'browser_unavailable',
        location_error: '当前浏览器不支持定位',
      };
    }
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: false,
          timeout: 8000,
          maximumAge: 10 * 60 * 1000,
        });
      });
      return {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        location_label: '浏览器定位',
        location_source: 'browser',
      };
    } catch (error) {
      const reason = geolocationErrorText(error);
      return {
        location_label: '用户未提供地点',
        location_source: 'browser_failed',
        location_error: reason,
      };
    }
  }

  async function streamAgentMessage(messageId: string, fullText: string, response: CaseResponse) {
    const chunkSize = 8;
    for (let index = 0; index < fullText.length; index += chunkSize) {
      const next = fullText.slice(0, index + chunkSize);
      setMessages((current) =>
        current.map((item) =>
          item.id === messageId
            ? {
                ...item,
                content: next,
                pending: index + chunkSize < fullText.length,
                response,
              }
            : item,
        ),
      );
      await new Promise((resolve) => window.setTimeout(resolve, 18));
    }
    setMessages((current) =>
      current.map((item) =>
        item.id === messageId
          ? {
              ...item,
              content: fullText,
              pending: false,
              response,
            }
          : item,
      ),
    );
  }

  function handleNewConversation() {
    setUserId(currentUser ? String(currentUser.id) : createDebugUserId());
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
                        {item.suspected_problem || '待判断'} · {formatDate(item.followup_date)}
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
                  {caseDetail?.title || (selectedCaseId ? '当前病例' : '尚未创建病例')}
                </Text>
              </Space>
              <Space>
                <Button
                  icon={<DownloadOutlined />}
                  disabled={!selectedCaseId}
                  onClick={() => void handleDownloadReport()}
                >
                  报告
                </Button>
              </Space>
            </div>

            <div className="message-stream" ref={messageStreamRef}>
              {messages.map((item) => (
                <div key={item.id} className={`chat-bubble ${item.role}${item.pending ? ' pending' : ''}`}>
                  <div className="bubble-role">{item.role === 'user' ? '用户' : 'Agent'}</div>
                  <Paragraph>{item.content}</Paragraph>
                  {item.pending ? <ThinkingIndicator label={pendingStep} /> : null}
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
                  placeholder="直接说你看到的情况、你的猜测，或这几天有没有变化..."
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
                    <InfoLine label="地点" value={environmentSummary(caseDetail).location} />
                    <InfoLine label="天气" value={environmentSummary(caseDetail).weather} />
                    <InfoLine label="阶段" value={stageSummary(caseDetail)} />
                    <InfoLine
                      label="采收"
                      value={harvestSummary(caseDetail)}
                    />
                    <InfoLine label="上次咨询日期" value={formatDate(caseDetail.created_at)} />
                    <InfoLine label="下次复查日期" value={formatDate(caseDetail.followup_date)} />
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

              <Card size="small" title={<PanelTitle icon={<SafetyCertificateOutlined />} text="Agent 运行轨迹" />}>
                {caseDetail ? <AgentTracePanel detail={caseDetail} /> : <Empty description="暂无 Agent 轨迹" />}
              </Card>

              <Card size="small" title={<PanelTitle icon={<ReloadOutlined />} text="工具调用" />}>
                {caseDetail ? <ToolCallPanel detail={caseDetail} /> : <Empty description="暂无工具调用" />}
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
    window.location.href = oauthStartUrl(provider.toLowerCase() as 'google' | 'github');
  }

  return (
    <main className="login-page">
      <div className="login-backdrop" />
      <div className="login-ambient ambient-one" />
      <div className="login-ambient ambient-two" />
      <div className="login-light-beam" />
      <div className="login-particles" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>

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
        <div className="login-form-halo" />
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

function mergeChatMessages(base: ChatMessage[], overlay: ChatMessage[]): ChatMessage[] {
  const seen = new Set<string>();
  return [...base, ...overlay].filter((item) => {
    const signature = `${item.id}|${item.role}|${item.content}`;
    if (seen.has(signature)) return false;
    seen.add(signature);
    return true;
  });
}

function caseDetailToMessages(detail: CaseDetail): ChatMessage[] {
  const events = [...detail.events].sort((left, right) => {
    const timeDiff = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
    if (timeDiff !== 0) return timeDiff;
    return left.id - right.id;
  });
  const userMessageInputs = new Set(
    events
      .filter((event) => event.event_type === 'USER_MESSAGE' && event.user_input)
      .map((event) => normalizeMessageText(event.user_input || '')),
  );
  const hasAgentResponses = events.some((event) => event.event_type === 'AGENT_RESPONSE');
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
      if (userMessageInputs.has(normalizeMessageText(event.user_input || ''))) return [];
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

    if (!hasAgentResponses && event.event_type === 'QUESTIONS_ASKED') {
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

    if (!hasAgentResponses && event.event_type === 'FOLLOWUP_COMPARED') {
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

function normalizeMessageText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function legacyPlanMessage(detail: CaseDetail) {
  const lines = ['已形成保守的初步判断，并创建复查计划。'];
  if (detail.suspected_problem || detail.likelihood) {
    lines.push('', `疑似问题：${detail.suspected_problem || '-'} / ${detail.likelihood || '-'}`);
  }
  if (detail.followup_date) {
    lines.push(`下次复查日期：${formatDate(detail.followup_date)}`);
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

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="thinking-indicator" aria-live="polite">
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <Text type="secondary">{label}</Text>
    </div>
  );
}

function ImageEvidence({ detail, onPreview }: { detail: CaseDetail; onPreview: (url: string) => void }) {
  const imageEvidence = Array.isArray(detail.structured_data.image_evidence)
    ? (detail.structured_data.image_evidence as string[])
    : [];
  const vision = detail.structured_data.vision_observation as
    | {
        status?: string;
        observed_parts?: string[];
        visual_symptoms?: string[];
        possible_problems?: string[];
        severity_signals?: string[];
        uncertainties?: string[];
        confidence?: string;
        model?: string;
      }
    | undefined;
  const analysisStatus = String(detail.structured_data.image_analysis_status || vision?.status || 'pending');
  const statusLabel: Record<string, string> = {
    analyzed: '视觉识别已完成',
    failed: '视觉识别调用失败',
    not_configured: '视觉识别未配置',
    not_supported: '当前模型不支持视觉识别',
    pending: '等待视觉识别',
  };
  if (!imageEvidence.length) return null;
  return (
    <Alert
      type={analysisStatus === 'analyzed' ? 'success' : analysisStatus === 'failed' ? 'warning' : 'info'}
      showIcon
      message={statusLabel[analysisStatus] || `图片分析状态：${analysisStatus}`}
      description={
        <Space direction="vertical" size={8} className="full-width">
          {vision ? (
            <Space direction="vertical" size={4} className="full-width">
              <Text type="secondary">
                模型：{vision.model || '-'} · 置信度：{vision.confidence || '-'}
              </Text>
              <CompactList label="观察部位" values={vision.observed_parts} />
              <CompactList label="可见症状" values={vision.visual_symptoms} />
              <CompactList label="候选问题" values={vision.possible_problems} />
              <CompactList label="严重线索" values={vision.severity_signals} />
              <CompactList label="不确定点" values={vision.uncertainties} />
            </Space>
          ) : (
            <Text type="secondary">图片已保存，等待视觉工具返回观察结果。</Text>
          )}
          <ImageStrip urls={imageEvidence} onPreview={onPreview} />
        </Space>
      }
    />
  );
}

function environmentSummary(detail: CaseDetail) {
  const locationObservation = detail.structured_data.location_observation as
    | {
        location?: string;
        location_source?: string;
      }
    | undefined;
  const weather = detail.structured_data.weather_observation as
    | {
        location?: string;
        location_source?: string;
        location_error?: string | null;
        status?: string;
        provider?: string;
        current_temperature_c?: number | null;
        current_relative_humidity?: number | null;
        current_precipitation_mm?: number | null;
        latitude?: number | null;
        longitude?: number | null;
        risk_signals?: string[];
        uncertainties?: string[];
        requires_confirmation?: boolean;
      }
    | undefined;
  const observedLocation = locationTextOrFallback(locationObservation?.location, '');
  if (!weather) return { location: observedLocation || '暂未识别出', weather: detail.recent_weather || '-' };

  const metrics = [
    weather.current_temperature_c != null ? `${weather.current_temperature_c}℃` : null,
    weather.current_relative_humidity != null ? `湿度 ${weather.current_relative_humidity}%` : null,
    weather.current_precipitation_mm != null ? `降水 ${weather.current_precipitation_mm}mm` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const weatherText =
    metrics ||
    weather.risk_signals?.slice(0, 2).join('；') ||
    weather.uncertainties?.slice(0, 1).join('；') ||
    detail.recent_weather ||
    String(weather.status || '-');
  return {
    location: observedLocation || locationTextOrFallback(weather.location, '暂未识别出'),
    weather: weatherText,
  };
}

function stageSummary(detail: CaseDetail) {
  const vision = detail.structured_data.vision_observation as { growth_stage_hint?: string | null } | undefined;
  return readableTextOrFallback(detail.growth_stage, readableTextOrFallback(vision?.growth_stage_hint));
}

function harvestSummary(detail: CaseDetail) {
  const vision = detail.structured_data.vision_observation as { harvest_hint?: string | null } | undefined;
  if (detail.days_to_harvest == null && vision?.harvest_hint) return vision.harvest_hint;
  if (detail.days_to_harvest == null) return '暂未识别出';
  if (vision?.harvest_hint) return `${detail.days_to_harvest} 天 · ${vision.harvest_hint}`;
  return `${detail.days_to_harvest} 天`;
}

function readableTextOrFallback(value?: unknown, fallback = '暂未识别出') {
  if (!value) return fallback;
  const text = String(value).trim();
  if (!text) return fallback;
  if (/[�]/.test(text)) return fallback;
  const suspiciousMatches = text.match(/[鐣鎴鍙绂鏋闇澶浣]/g);
  if (suspiciousMatches && suspiciousMatches.length >= Math.max(2, Math.ceil(text.length * 0.25))) {
    return fallback;
  }
  return text;
}

function locationTextOrFallback(value?: unknown, fallback = '暂未识别出') {
  const text = readableTextOrFallback(value, '');
  if (!text || text === '用户未提供地点' || text === '当前位置附近') return fallback;
  return text;
}

function CompactList({ label, values }: { label: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <Text type="secondary">
      {label}：{values.slice(0, 4).join('、')}
    </Text>
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
                <Text strong>复查提醒</Text>
                <Text type="secondary">{dayjs(item.due_at).format('YYYY-MM-DD HH:mm')}</Text>
              </Space>
              <Text type="secondary">{item.reason || '系统提醒复查番茄异常处置效果'}</Text>
              <Space size={8}>
                {item.calendar_url ? (
                  <Button size="small" href={item.calendar_url} target="_blank">
                    加入 Google 日历
                  </Button>
                ) : null}
                {item.ics_url ? (
                  <Button size="small" href={apiUrl(item.ics_url)} target="_blank">
                    下载 ICS
                  </Button>
                ) : null}
              </Space>
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

function AgentTracePanel({ detail }: { detail: CaseDetail }) {
  const decisionEvent = [...detail.events].reverse().find((event) => event.event_type === 'AGENT_DECISION');
  const trace = decisionEvent?.system_output.trace as AgentTrace | undefined;
  if (!trace) return <Empty description="暂无 Agent 决策轨迹" />;

  const observe = trace.observe || {};
  const decide = trace.decide || {};
  const act = trace.act || {};
  const guard = trace.guard || {};
  const memory = trace.memory || {};

  return (
    <Space direction="vertical" size={10} className="full-width agent-trace">
      <div className="trace-row">
        <Text strong>Observe</Text>
        <Space wrap size={4}>
          <Tag>{String(observe.case_status || '-')}</Tag>
          {observe.vision_status ? <Tag color="cyan">Vision {String(observe.vision_status)}</Tag> : null}
          {observe.active_followup ? <Tag color="purple">Follow-up</Tag> : null}
        </Space>
      </div>
      <TraceList label="观察依据" values={decide.observations_used} />

      <div className="trace-row">
        <Text strong>Decide</Text>
        <Space wrap size={4}>
          <Tag color={String(decide.source || '').startsWith('llm') ? 'green' : 'gold'}>
            {String(decide.source || 'rule')}
          </Tag>
          <Tag color="blue">{String(decide.next_action || '-')}</Tag>
          {decide.requested_state ? <Tag>{decide.requested_state}</Tag> : null}
          {decide.confidence ? <Tag>{decide.confidence}</Tag> : null}
          {decide.user_intent ? <Tag color="geekblue">{decide.user_intent}</Tag> : null}
        </Space>
      </div>
      {decide.reason ? <Text type="secondary">{decide.reason}</Text> : null}
      {decide.fallback_reason ? <Alert type="warning" showIcon message={decide.fallback_reason} /> : null}

      <TraceList label="本轮回答焦点" values={decide.response_focus} />
      <TraceList label="Act 工具计划" values={act.planned_tools} />
      <TraceList label="Guard 约束" values={guard.guardrails} />
      <TraceList label="Memory 写入" values={memory.will_write_events} />
      <Collapse
        size="small"
        ghost
        items={[
          tracePanelItem('Observe 输入', observe.input),
          tracePanelItem('Observe 输出', observe.output),
          tracePanelItem('Decide 输入', decide.input),
          tracePanelItem('Decide 输出', decide.output),
          tracePanelItem('Act 输入', act.input),
          tracePanelItem('Act 输出', act.output),
          tracePanelItem('Guard 输入', guard.input),
          tracePanelItem('Guard 输出', guard.output),
          tracePanelItem('Memory 输入', memory.input),
          tracePanelItem('Memory 输出', memory.output),
        ].filter(isTracePanelItem)}
      />
    </Space>
  );
}

function tracePanelItem(label: string, payload?: Record<string, unknown>) {
  if (!payload || !Object.keys(payload).length) return null;
  return {
    key: label,
    label,
    children: <JsonBlock value={payload} />,
  };
}

function isTracePanelItem(
  item: ReturnType<typeof tracePanelItem>,
): item is Exclude<ReturnType<typeof tracePanelItem>, null> {
  return item !== null;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

function TraceList({ label, values }: { label: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <Space direction="vertical" size={4} className="full-width">
      <Text strong>{label}</Text>
      <div className="trace-tags">
        {values.slice(0, 8).map((item, index) => (
          <Tag key={`${item}-${index}`}>{item}</Tag>
        ))}
      </div>
    </Space>
  );
}

function ToolCallPanel({ detail }: { detail: CaseDetail }) {
  const toolEvents = detail.events
    .filter((event) => event.event_type === 'TOOL_CALLED')
    .slice(-10)
    .reverse();

  if (!toolEvents.length) return <Empty description="暂无工具调用记录" />;

  return (
    <Space direction="vertical" size={8} className="full-width tool-call-panel">
      {toolEvents.map((event) => {
        const tool = String(event.system_output.tool || '-');
        const ok = event.system_output.ok !== false;
        const output = event.system_output.output as Record<string, unknown> | undefined;
        return (
          <div className="tool-call-row" key={event.id}>
            <Space wrap size={4}>
              <Tag color={ok ? toolColor(tool) : 'red'}>{tool}</Tag>
              <Text type="secondary">{dayjs(event.created_at).format('MM-DD HH:mm')}</Text>
            </Space>
            <Text type="secondary">{toolSummary(tool, output)}</Text>
            {tool === 'CalendarReminderTool' && output ? (
              <Space size={8} className="calendar-actions">
                {typeof output.calendar_url === 'string' ? (
                  <Button size="small" href={output.calendar_url} target="_blank">
                    加入 Google 日历
                  </Button>
                ) : null}
                {typeof output.ics_url === 'string' ? (
                  <Button size="small" href={apiUrl(output.ics_url)} target="_blank">
                    下载 ICS
                  </Button>
                ) : null}
              </Space>
            ) : null}
          </div>
        );
      })}
    </Space>
  );
}

function toolColor(tool: string) {
  if (tool.includes('Date')) return 'blue';
  if (tool.includes('Location')) return 'lime';
  if (tool.includes('Weather')) return 'cyan';
  if (tool.includes('Calendar') || tool.includes('Reminder')) return 'purple';
  if (tool.includes('Safety')) return 'green';
  if (tool.includes('Vision')) return 'magenta';
  return 'default';
}

function toolSummary(tool: string, output?: Record<string, unknown>) {
  if (!output) return '已调用，暂无可展示输出';
  if (tool === 'DateTool') {
    return `当前日期：${String(output.today || '-')} · 时区：${String(output.timezone || '-')}`;
  }
  if (tool === 'LocationTool') {
    const error = output.location_error ? ` · ${String(output.location_error)}` : '';
    return `地点：${String(output.location || '-')} · 来源：${String(output.location_source || '-')}${error}`;
  }
  if (tool === 'WeatherTool') {
    const signals = Array.isArray(output.risk_signals) ? output.risk_signals.join('；') : '';
    const uncertainties = Array.isArray(output.uncertainties) ? output.uncertainties.join('；') : '';
    const weather = [
      output.current_temperature_c != null ? `${String(output.current_temperature_c)}℃` : null,
      output.current_relative_humidity != null ? `湿度 ${String(output.current_relative_humidity)}%` : null,
      output.current_precipitation_mm != null ? `降水 ${String(output.current_precipitation_mm)}mm` : null,
    ]
      .filter(Boolean)
      .join(' · ');
    return `地点：${String(output.location || '-')} · 来源：${String(output.location_source || '-')} · ${weather || String(output.status || '-')} · ${signals || uncertainties || '未发现明显天气风险信号'}`;
  }
  if (tool === 'CalendarReminderTool') {
    return `复查：${String(output.due_date || '-')} · ${String(output.mode || '-')} · ${String(output.channel || '-')}`;
  }
  if (tool === 'SafetyChecker') {
    return `风险：${String(output.risk_level || '-')} · ${Array.isArray(output.warnings) ? output.warnings.slice(0, 2).join('；') : ''}`;
  }
  if (tool === 'VisionTool') {
    const problems = Array.isArray(output.possible_problems) ? output.possible_problems.join('、') : '';
    return `状态：${String(output.status || '-')} · 候选：${problems || '-'}`;
  }
  if (tool === 'ResponseComposer') {
    return '已将结构化结果整理为用户可读回复';
  }
  return '已调用并写入事件记忆';
}

function EventTimeline({ detail, limit }: { detail: CaseDetail; limit: number }) {
  const items = detail.events.slice(-limit).reverse().map((event) => ({
    color: event.event_type === 'STATE_CHANGED' ? 'green' : 'blue',
    children: (
      <Space direction="vertical" size={2}>
        <Space>
          <Text strong>{event.event_type}</Text>
          {event.event_type === 'TOOL_CALLED' && event.system_output.tool ? (
            <Tag color={event.system_output.ok === false ? 'red' : 'cyan'}>{String(event.system_output.tool)}</Tag>
          ) : null}
          <Text type="secondary">{dayjs(event.created_at).format('MM-DD HH:mm')}</Text>
        </Space>
        {event.user_input ? <Text type="secondary">{event.user_input}</Text> : null}
      </Space>
    ),
  }));
  return <Timeline items={items} />;
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
