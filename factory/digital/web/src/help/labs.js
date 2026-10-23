// 帮助里能嵌的虚拟实验（第 30 轮 §八 8-1，```lab id: 名字```）：页面在 web/public/labs/<名字>.html，
// 是《数字工厂实训》网页版 textbook/web-editions/dfactory/src/zh/labs/ 的副本（factory/digital/tools/sync_help_labs.py 同步）。
// presets：实验页里的预置按钮（data-p），块里写 preset: 名字 就替你点上。
export const LABS = {
  causal: { title: '一次停机的因果链', what: '拖停机时长、时刻，看因果链一层层亮到客户', caption: '课程《数字工厂实训》动画 3-1',
    presets: ['book', 'lab', 'long', 'rush', 'fri'] },
  whatif: { title: '加班、加急还是外协', what: '四个方案各推演一遍，比多花的钱和交期', caption: '课程《数字工厂实训》实验 3-2',
    presets: ['book', 'd30', 'd40', 'dec'] },
  weibull: { title: '威布尔可靠性：设备还能撑多久', what: '拖 β、η、已运行小时，看未来坏掉的概率', caption: '课程《数字工厂实训》实验 6-1',
    presets: ['grd', 'cnc', 'ht', 'exp'] },
  pmopt: { title: '保养周期怎样定', what: '拖保养周期，找长期平均花费的最低点', caption: '课程《数字工厂实训》实验 6-2',
    presets: ['after', 'during', 'exp'] },
  waterfall: { title: '订单毛利瀑布：钱都去哪儿了', what: '拖单价、料价、工时，看毛利一块块被切掉', caption: '课程《数字工厂实训》实验 10-1',
    presets: ['robot', 'std', 'cut'] },
  cashflow: { title: '未来 8 周的现金：客户哪天付', what: '点不处理、催款、信用冻结，看现金最低的一周', caption: '课程《数字工厂实训》实验 10-2',
    presets: ['none', 'dun', 'hold'] },
};
