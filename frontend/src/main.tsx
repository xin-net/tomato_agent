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
  message,
  theme,
} from 'antd';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import dayjs from 'dayjs';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  closeCase,
  getCase,
  listCases,
  sendConversationMessage,
  submitFollowup,
} from './api';
import { buildStateMachineElements, caseStatusLabels } from './stateMachine';
import type { CaseDetail, CaseListItem, CaseResponse, CaseStatus, ChatMessage } from './types';

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
  const [userId, setUserId] = useState(createDebugUserId);
  const [loadingCases, setLoadingCases] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sending, setSending] = useState(false);
  const [filter, setFilter] = useState<string>('active');
  const [followupOpen, setFollowupOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);

  const activeStatus = caseDetail?.status || messages.findLast((item) => item.response)?.response?.status;
  const { nodes, edges } = useMemo(
    () => buildStateMachineElements(activeStatus || null),
    [activeStatus],
  );

  const refreshCases = useCallback(async () => {
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
      setCaseDetail(await getCase(caseId));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '病例详情加载失败');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    void refreshCases();
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
    if (!text) return;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text };
    setMessages((current) => [...current, userMessage]);
    setInput('');
    setSending(true);
    try {
      const result = await sendConversationMessage({
        user_id: userId,
        case_id: selectedCaseId,
        message: text,
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

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <Space direction="vertical" size={0}>
          <Title level={3}>Tomato Case Agent</Title>
          <Text type="secondary">Conversation → Case → Decision → Guardrails → Tools → Memory → Follow-up</Text>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refreshCases()}>
            刷新
          </Button>
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
              </Space>
            </div>

            <div className="message-stream">
              {messages.map((item) => (
                <div key={item.id} className={`chat-bubble ${item.role}`}>
                  <div className="bubble-role">{item.role === 'user' ? '用户' : 'Agent'}</div>
                  <Paragraph>{item.content}</Paragraph>
                </div>
              ))}
            </div>

            <div className="composer">
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
              <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={() => void handleSend()}>
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
                    <InfoLine label="复查日期" value={formatDate(caseDetail.followup_date)} />
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
                    <EventTimeline detail={caseDetail} />
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
    </Layout>
  );
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

function EventTimeline({ detail }: { detail: CaseDetail }) {
  const items = detail.events.slice(-8).reverse().map((event) => ({
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
