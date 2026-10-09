"""薄膜电机学习路径：固定知识骨架，动态挂接检索论文。"""
from __future__ import annotations

from typing import Iterator, Optional

FM = "film_motor"

# ---------------------------------------------------------------- 静电薄膜电机
TREE_FM = {
    "id": "fm_root",
    "label": "静电薄膜电机",
    "en": "Electrostatic Film Motor",
    "desc": "用静电力推动滑块产生相对运动：推力从哪来、上限在哪、怎么控制",
    "children": [
        {
            "id": "fm_fund", "label": "一、物理基础", "en": "Fundamentals", "level": 1,
            "desc": "先搞清楚推力从哪来、天花板在哪 —— 这决定了后面所有设计的取舍",
            "children": [
                {"id": "fm_force", "label": "静电力与切向推力", "en": "Electrostatic tangential force",
                 "level": 1, "desc": "电极错位产生的切向分量才是推力来源；力正比于电压平方、反比于间距平方",
                 "q": "electrostatic tangential force thrust Maxwell stress electrode overlap film actuator"},
                {"id": "fm_dielectric", "label": "介电材料与电荷弛豫", "en": "Dielectric & charge relaxation",
                 "level": 1, "desc": "体电阻率决定电荷弛豫时间，进而决定能用多高的驱动频率",
                 "q": "dielectric constant volume resistivity charge relaxation time constant film material"},
                {"id": "fm_breakdown", "label": "击穿限制与 Paschen 定律", "en": "Breakdown limit",
                 "level": 1, "desc": "推力想大就要提高场强，但会击穿。间距越小反而能承受更高场强",
                 "q": "breakdown voltage Paschen law electric field limit air gap insulation electrostatic actuator"},
                {"id": "fm_electret", "label": "驻极体与电荷保持", "en": "Electret",
                 "level": 2, "desc": "用永久驻留电荷替代外加高压，是低压驱动的主要思路",
                 "q": "electret charge retention surface potential corona charging low voltage electrostatic motor"},
            ],
        },
        {
            "id": "fm_mech", "label": "二、驱动原理", "en": "Driving principles", "level": 2,
            "desc": "同样是静电力，让滑块动起来有几条完全不同的技术路线",
            "children": [
                {"id": "fm_induction", "label": "感应式驱动", "en": "Induction type", "level": 2,
                 "desc": "行波电场在高阻滑块上感应电荷，异步拖动。滑块不需要预充电或布线",
                 "q": "induction type electrostatic motor traveling wave slip high resistivity slider asynchronous"},
                {"id": "fm_sync", "label": "同步 / 电压驱动式", "en": "Synchronous type", "level": 2,
                 "desc": "滑块自带电极并施加电压，与定子同步。推力大但要给滑块供电",
                 "q": "synchronous electrostatic film motor voltage driven stator slider electrode phase"},
                {"id": "fm_dual", "label": "双激励多相驱动", "en": "Dual excitation multiphase", "level": 3,
                 "desc": "Higuchi 组的标志性方案：定子滑块双边同时激励，推力显著提升",
                 "q": "dual excitation multiphase electrostatic drive Niino Higuchi thrust improvement"},
                {"id": "fm_charge", "label": "电荷感应式与其他变体", "en": "Charge induction & variants",
                 "level": 3, "desc": "电荷注入、混合激励等衍生方案，各自的适用边界",
                 "q": "charge induction electrostatic motor hybrid excitation variant scheme comparison"},
            ],
        },
        {
            "id": "fm_dev", "label": "三、器件与工艺", "en": "Devices & fabrication", "level": 2,
            "desc": "从原理到能用的东西：电极怎么排、怎么叠、怎么做出来",
            "children": [
                {"id": "fm_electrode", "label": "电极设计：节距与间距", "en": "Electrode pitch & gap",
                 "level": 2, "desc": "节距、间距、占空比如何权衡推力与击穿风险",
                 "q": "electrode pitch spacing gap width design thrust optimization electrode pattern film motor"},
                {"id": "fm_multilayer", "label": "多层堆叠结构", "en": "Multi-layer stacking", "level": 3,
                 "desc": "多层薄膜叠起来成倍放大推力，是提高推力密度最直接的路子",
                 "q": "multi-layer multilayered stacked electrostatic film actuator thrust density"},
                {"id": "fm_fab", "label": "柔性基底与制造工艺", "en": "Flexible substrate & fabrication",
                 "level": 3, "desc": "印刷、光刻、卷对卷在柔性电极上的应用",
                 "q": "fabrication printing photolithography flexible substrate electrode film actuator process"},
            ],
        },
        {
            "id": "fm_model", "label": "四、建模与控制", "en": "Modeling & control", "level": 3,
            "desc": "从能动到能精确控制，这一层决定它能不能真的用进系统",
            "children": [
                {"id": "fm_analytic", "label": "解析模型与等效电路", "en": "Analytical model", "level": 3,
                 "desc": "推力-位移-电压的解析表达与参数辨识",
                 "q": "analytical model equivalent circuit identification electrostatic motor simulation thrust"},
                {"id": "fm_sensing", "label": "位置自感知", "en": "Position self-sensing", "level": 3,
                 "desc": "不加外部传感器，从驱动电极的电学量反推滑块位置",
                 "q": "position self-sensing sensorless slider detection capacitance charge induction estimation"},
                {"id": "fm_control", "label": "力控制与闭环", "en": "Force control", "level": 3,
                 "desc": "输出力的闭环调节、迟滞与蠕变补偿",
                 "q": "force control closed loop feedback hysteresis creep compensation electrostatic actuator"},
            ],
        },
        {
            "id": "fm_app", "label": "五、应用", "en": "Applications", "level": 2,
            "desc": "最终用在哪里，以及各自的约束",
            "children": [
                {"id": "fm_robot", "label": "机器人与人工肌肉", "en": "Robotics & artificial muscle",
                 "level": 2, "desc": "柔性驱动、仿生运动、软体机器人",
                 "q": "robot actuator artificial muscle soft robotics bio-inspired electrostatic film drive"},
                {"id": "fm_precision", "label": "精密定位与微操作", "en": "Precision positioning", "level": 3,
                 "desc": "长行程平面定位、微操作台",
                 "q": "precision positioning long stroke planar stage micromanipulation electrostatic actuator"},
                {"id": "fm_special", "label": "特殊环境应用", "en": "Special environments", "level": 3,
                 "desc": "MR 兼容、真空、强磁场等场合 —— 无磁性是静电驱动的独有优势",
                 "q": "MRI compatible nonmagnetic vacuum environment electrostatic actuator special application"},
            ],
        },
    ],
}

TREES = {FM: TREE_FM}
TREE = TREE_FM


def get_tree(domain: Optional[str] = None) -> dict:
    if domain not in (None, FM):
        raise ValueError("只支持 film_motor")
    return TREE_FM


def walk(node: Optional[dict] = None) -> Iterator[dict]:
    node = node if node is not None else TREE
    yield node
    for ch in node.get("children", []):
        yield from walk(ch)


def leaves(domain: Optional[str] = None) -> list:
    return [n for n in walk(get_tree(domain)) if not n.get("children")]


def find(node_id: str, domain: Optional[str] = None) -> Optional[dict]:
    for n in walk(get_tree(domain)):
        if n["id"] == node_id:
            return n
    return None


def domain_of(node_id: str) -> Optional[str]:
    """节点属于哪个领域 —— 检索时用它把召回限定在对应大类。"""
    for d, t in TREES.items():
        if any(n["id"] == node_id for n in walk(t)):
            return d
    return None


def outline(domain: Optional[str] = None) -> str:
    """给大模型看的树形大纲，用来把问题定位到节点。"""
    lines = []
    for top in get_tree(domain).get("children", []):
        # 合并树多一层，展开到叶节点所在的那一层
        if top.get("id") in TREES:
            lines.append(f"# {top['label']}")
            groups = top.get("children", [])
        else:
            groups = [top]
        for g in groups:
            lines.append(f"{g['label']}")
            for ch in g.get("children", []):
                lines.append(f"  - {ch['id']}: {ch['label']}（{ch['en']}）{ch['desc']}")
    return "\n".join(lines)


def skeleton(domain: Optional[str] = None) -> dict:
    """去掉查询词的纯结构，给前端画图用。"""
    def strip(n):
        out = {k: v for k, v in n.items() if k != "q"}
        if n.get("children"):
            out["children"] = [strip(c) for c in n["children"]]
        return out
    return strip(get_tree(domain))
