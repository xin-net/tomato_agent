import { MarkerType, type Edge, type Node } from '@xyflow/react';
import type { CaseStatus } from './types';

export const caseStatusLabels: Record<CaseStatus, string> = {
  NEW: '新病例',
  NEED_MORE_INFO: '待补充',
  DIAGNOSED: '已诊断',
  FOLLOWUP_PENDING: '待复查',
  FOLLOWUP_REVIEW: '复查判断',
  IMPROVING: '好转',
  WORSENING: '恶化',
  ESCALATED: '人工确认',
  CLOSED: '已结案',
};

export const caseStatusTransitions: Record<CaseStatus, CaseStatus[]> = {
  NEW: ['NEED_MORE_INFO', 'FOLLOWUP_PENDING', 'ESCALATED'],
  NEED_MORE_INFO: ['NEED_MORE_INFO', 'FOLLOWUP_PENDING', 'ESCALATED'],
  DIAGNOSED: ['FOLLOWUP_PENDING', 'ESCALATED'],
  FOLLOWUP_PENDING: ['FOLLOWUP_REVIEW', 'ESCALATED'],
  FOLLOWUP_REVIEW: ['IMPROVING', 'WORSENING', 'ESCALATED', 'NEED_MORE_INFO', 'CLOSED'],
  IMPROVING: ['FOLLOWUP_PENDING', 'CLOSED', 'ESCALATED'],
  WORSENING: ['ESCALATED', 'FOLLOWUP_PENDING'],
  ESCALATED: ['CLOSED'],
  CLOSED: [],
};

const positions: Record<CaseStatus, { x: number; y: number }> = {
  NEW: { x: 260, y: 0 },
  NEED_MORE_INFO: { x: 70, y: 115 },
  DIAGNOSED: { x: 450, y: 115 },
  FOLLOWUP_PENDING: { x: 260, y: 230 },
  FOLLOWUP_REVIEW: { x: 260, y: 345 },
  IMPROVING: { x: 20, y: 470 },
  WORSENING: { x: 260, y: 470 },
  ESCALATED: { x: 500, y: 470 },
  CLOSED: { x: 260, y: 600 },
};

export function buildStateMachineElements(activeStatus?: CaseStatus | null): {
  nodes: Node[];
  edges: Edge[];
} {
  const nextStates = activeStatus ? new Set(caseStatusTransitions[activeStatus]) : new Set();

  const nodes = (Object.keys(caseStatusLabels) as CaseStatus[]).map((status) => ({
    id: status,
    type: 'default',
    position: positions[status],
    draggable: false,
    data: {
      label: `${status}\n${caseStatusLabels[status]}`,
    },
    className: [
      'status-node',
      status === activeStatus ? 'status-node-active' : '',
      nextStates.has(status) ? 'status-node-next' : '',
      status === 'DIAGNOSED' ? 'status-node-reserved' : '',
      status === 'ESCALATED' || status === 'WORSENING' ? 'status-node-danger' : '',
      status === 'CLOSED' ? 'status-node-done' : '',
    ]
      .filter(Boolean)
      .join(' '),
  }));

  const edges = Object.entries(caseStatusTransitions).flatMap(([source, targets]) =>
    targets.map((target) => {
      const isActiveEdge = source === activeStatus;
      return {
        id: `${source}-${target}`,
        source,
        target,
        animated: isActiveEdge,
        markerEnd: { type: MarkerType.ArrowClosed },
        className: isActiveEdge ? 'status-edge-active' : 'status-edge',
        style: {
          stroke: isActiveEdge ? '#2f7d4a' : '#c9d3c6',
          strokeWidth: isActiveEdge ? 2.5 : 1.4,
        },
      };
    }),
  );

  return { nodes, edges };
}
