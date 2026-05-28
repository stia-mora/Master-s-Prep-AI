const DEFAULT_USER_ID = "local-user";

const SUBJECTS = [
  {
    id: "computer408",
    name: "计算机 408",
    shortName: "408",
    description: "计算机学科专业基础综合，包含数据结构、组成原理、操作系统、计算机网络。",
    available: true
  }
];

const SUBJECT_PLAN_408 = {
  subject: "408计算机",
  totalPoints: 150,
  totalMinutes: 180,
  choiceTotal: 40,
  comprehensiveTotal: 7,
  modules: [
    {
      id: "data_structure",
      name: "数据结构",
      shortName: "数据结构",
      points: 45,
      choiceCount: 10,
      comprehensiveCount: 2,
      choiceRange: [1, 10],
      comprehensiveNumbers: [41, 42],
      explanation: "线性表、树图、查找排序，重在结构选择和算法设计。"
    },
    {
      id: "computer_organization",
      name: "计算机组成原理",
      shortName: "组成原理",
      points: 45,
      choiceCount: 12,
      comprehensiveCount: 3,
      choiceRange: [11, 22],
      comprehensiveNumbers: [43, 44, 45],
      explanation: "数据表示、存储层次、指令与 CPU，重在硬件机制推理。"
    },
    {
      id: "operating_system",
      name: "操作系统",
      shortName: "操作系统",
      points: 35,
      choiceCount: 10,
      comprehensiveCount: 1,
      choiceRange: [23, 32],
      comprehensiveNumbers: [46],
      explanation: "进程、内存、文件与 I/O，重在状态变化和资源管理。"
    },
    {
      id: "computer_network",
      name: "计算机网络",
      shortName: "计算机网络",
      points: 25,
      choiceCount: 8,
      comprehensiveCount: 1,
      choiceRange: [33, 40],
      comprehensiveNumbers: [47],
      explanation: "协议、传输、路由与应用层，重在分层和时延计算。"
    }
  ]
};

const QUESTION_TYPE_LABELS = {
  choice: "单项选择题",
  comprehensive: "综合应用题"
};

const SOURCE_SCOPES = {
  all: "全部 Markdown 数据",
  exam408: "仅 408 真题",
  practice: "仅练习题"
};

function moduleById(id) {
  return SUBJECT_PLAN_408.modules.find((item) => item.id === id);
}

function moduleFor408QuestionNumber(number) {
  const normalized = Number(number);
  if (!Number.isFinite(normalized)) return null;
  return SUBJECT_PLAN_408.modules.find((subjectModule) => {
    const [start, end] = subjectModule.choiceRange;
    return (
      (normalized >= start && normalized <= end) ||
      subjectModule.comprehensiveNumbers.includes(normalized)
    );
  }) || null;
}

function modulePercent(moduleId) {
  const subjectModule = moduleById(moduleId);
  if (!subjectModule) return 0;
  return Math.round((subjectModule.points / SUBJECT_PLAN_408.totalPoints) * 1000) / 10;
}

module.exports = {
  DEFAULT_USER_ID,
  QUESTION_TYPE_LABELS,
  SOURCE_SCOPES,
  SUBJECTS,
  SUBJECT_PLAN_408,
  moduleById,
  moduleFor408QuestionNumber,
  modulePercent
};
