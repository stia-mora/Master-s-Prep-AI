const DEFAULT_USER_ID = "local-user";

const SUBJECTS = [
  {
    id: "mathKaoyan",
    name: "考研数学",
    shortName: "数学",
    description: "以高等数学、线性代数、概率统计为核心的数学练习与组卷示例。",
    available: true
  }
];

const SUBJECT_PLAN_MATH = {
  subject: "考研数学",
  totalPoints: 150,
  totalMinutes: 180,
  choiceTotal: 10,
  comprehensiveTotal: 10,
  choicePoints: 5,
  modules: [
    {
      id: "advanced_math",
      name: "高等数学",
      shortName: "高数",
      points: 84,
      choiceCount: 5,
      comprehensiveCount: 6,
      choiceRange: [1, 5],
      comprehensiveNumbers: [11, 12, 13, 14, 15, 16],
      explanation: "函数、极限、导数、积分、级数和微分方程，重在运算与综合应用。"
    },
    {
      id: "linear_algebra",
      name: "线性代数",
      shortName: "线代",
      points: 33,
      choiceCount: 3,
      comprehensiveCount: 2,
      choiceRange: [6, 8],
      comprehensiveNumbers: [17, 18],
      explanation: "行列式、矩阵、向量、线性方程组、特征值与二次型。"
    },
    {
      id: "probability",
      name: "概率统计",
      shortName: "概率",
      points: 33,
      choiceCount: 2,
      comprehensiveCount: 2,
      choiceRange: [9, 10],
      comprehensiveNumbers: [19, 20],
      explanation: "随机事件、随机变量、分布、数字特征和参数估计。"
    }
  ]
};

const QUESTION_TYPE_LABELS = {
  choice: "选择题",
  comprehensive: "解答题"
};

const SOURCE_SCOPES = {
  all: "全部数学 Markdown 数据",
  examMath: "仅数学示例卷",
  practice: "仅数学练习题"
};

function moduleById(id) {
  return SUBJECT_PLAN_MATH.modules.find((item) => item.id === id);
}

function moduleForMathQuestionNumber(number) {
  const normalized = Number(number);
  if (!Number.isFinite(normalized)) return null;
  return SUBJECT_PLAN_MATH.modules.find((mathModule) => {
    const [start, end] = mathModule.choiceRange;
    return (
      (normalized >= start && normalized <= end) ||
      mathModule.comprehensiveNumbers.includes(normalized)
    );
  }) || null;
}

function modulePercent(moduleId) {
  const mathModule = moduleById(moduleId);
  if (!mathModule) return 0;
  return Math.round((mathModule.points / SUBJECT_PLAN_MATH.totalPoints) * 1000) / 10;
}

module.exports = {
  DEFAULT_USER_ID,
  QUESTION_TYPE_LABELS,
  SOURCE_SCOPES,
  SUBJECTS,
  SUBJECT_PLAN_MATH,
  moduleById,
  moduleForMathQuestionNumber,
  modulePercent
};
