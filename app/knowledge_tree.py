"""学习路径知识树。

固定骨架 + 动态挂论文：树的结构是我按语料里实际有的内容设计的，不由模型
现场生成 —— 模型生成的树每次都不一样，还会编造语料里根本没有的分支，
对「学习路径」这种要求稳定可信的场景是灾难。

每个节点带 `q`（检索用查询词），提问时把命中的论文挂到对应分支上。
`level` 是建议的学习阶段：1 入门 / 2 进阶 / 3 专题。
"""
from __future__ import annotations

from typing import Optional

FM, EA = "film_motor", "electroadhesion"

TREE = {
    "id": "root",
    "label": "静电驱动与静电吸附",
    "en": "Electrostatic Actuation & Adhesion",
    "desc": "以静电力做功的两大技术路线：让物体动起来（电机），和让物体粘住（吸附）",
    "children": [
        {
            "id": "fundamentals",
            "label": "一、物理基础",
            "en": "Fundamentals",
            "level": 1,
            "desc": "先搞清楚力从哪来、上限在哪 —— 这决定了后面所有设计的天花板",
            "children": [
                {"id": "f_force", "label": "静电力与麦克斯韦应力", "en": "Electrostatic force / Maxwell stress",
                 "level": 1, "cat": None,
                 "desc": "面积、电压、间距如何决定力的大小；为什么力正比于电压平方",
                 "q": "Maxwell stress tensor electrostatic force electric field energy density parallel plate"},
                {"id": "f_dielectric", "label": "介电材料与极化", "en": "Dielectric & polarization",
                 "level": 1, "cat": None,
                 "desc": "介电常数、极化弛豫、体电阻率如何影响出力和响应速度",
                 "q": "dielectric constant permittivity polarization relaxation volume resistivity material"},
                {"id": "f_breakdown", "label": "击穿与 Paschen 定律", "en": "Breakdown & Paschen's law",
                 "level": 1, "cat": None,
                 "desc": "静电驱动的根本瓶颈：想提高电场就会击穿。间距越小反而能加更高场强",
                 "q": "breakdown voltage Paschen law electric field limit air gap insulation dielectric strength"},
                {"id": "f_electret", "label": "驻极体与电荷保持", "en": "Electret & charge retention",
                 "level": 2, "cat": FM,
                 "desc": "用永久驻留电荷替代外加高压，实现低压驱动的思路",
                 "q": "electret charge retention surface potential corona charging low voltage bias"},
            ],
        },
        {
            "id": "mechanism",
            "label": "二、驱动与吸附机理",
            "en": "Mechanisms",
            "level": 2,
            "desc": "两条技术路线在这里分叉：让电荷推着走，还是让电荷吸住不动",
            "children": [
                {"id": "m_induction", "label": "感应式驱动", "en": "Induction type",
                 "level": 2, "cat": FM,
                 "desc": "靠行波电场在高阻滑块上感应出电荷，异步拖动。不需要滑块预充电",
                 "q": "induction type electrostatic motor traveling wave slip frequency high resistivity slider"},
                {"id": "m_synchronous", "label": "同步/电压驱动式", "en": "Synchronous / voltage type",
                 "level": 2, "cat": FM,
                 "desc": "滑块自带电极并施加电压，与定子同步。推力大但需给滑块布线",
                 "q": "synchronous electrostatic motor voltage driven film actuator stator slider electrode phase"},
                {"id": "m_dual", "label": "双激励多相驱动", "en": "Dual excitation multiphase",
                 "level": 3, "cat": FM,
                 "desc": "Higuchi 组的标志性方案：定子滑块双边同时激励，推力显著提升",
                 "q": "dual excitation multiphase electrostatic drive Niino Higuchi thrust improvement"},
                {"id": "m_ea_force", "label": "电粘附力机理", "en": "Electroadhesion mechanism",
                 "level": 2, "cat": EA,
                 "desc": "静电吸引 + Johnsen-Rahbek 效应；后者靠微观接触点漏电荷产生更大吸力",
                 "q": "electroadhesion mechanism Johnsen-Rahbek effect electrostatic attraction normal force"},
                {"id": "m_contact", "label": "接触界面与粗糙度", "en": "Contact interface & roughness",
                 "level": 3, "cat": EA,
                 "desc": "真实接触面积远小于表观面积，粗糙度直接决定吸附力能不能兑现",
                 "q": "surface roughness real contact area asperity interface electroadhesion rough"},
            ],
        },
        {
            "id": "device",
            "label": "三、器件与工艺",
            "en": "Devices & Fabrication",
            "level": 2,
            "desc": "从原理到能用的东西：电极怎么排、材料怎么选、怎么做出来",
            "children": [
                {"id": "d_electrode", "label": "电极设计：节距与间距", "en": "Electrode pitch & gap",
                 "level": 2, "cat": None,
                 "desc": "节距、间距、占空比如何权衡推力与击穿风险",
                 "q": "electrode pitch spacing gap width design thrust optimization electrode pattern"},
                {"id": "d_multilayer", "label": "多层堆叠结构", "en": "Multi-layer stacking",
                 "level": 3, "cat": FM,
                 "desc": "把多层薄膜叠起来成倍放大推力，是提高推力密度最直接的路子",
                 "q": "multi-layer multilayered stacked electrostatic film actuator thrust density"},
                {"id": "d_gripper", "label": "吸附垫与夹持器", "en": "Adhesion pads & grippers",
                 "level": 2, "cat": EA,
                 "desc": "电极图形（叉指/螺旋）、柔性基底、与软体气动的复合",
                 "q": "electroadhesive pad gripper interdigitated electrode flexible substrate soft gripper"},
                {"id": "d_clutch", "label": "静电离合器", "en": "Electrostatic clutch",
                 "level": 3, "cat": EA,
                 "desc": "可控通断的剪切耦合，可穿戴触觉和变刚度结构的核心部件",
                 "q": "electrostatic clutch electroadhesive clutch shear holding force wearable variable stiffness"},
                {"id": "d_fab", "label": "制造工艺", "en": "Fabrication",
                 "level": 3, "cat": None,
                 "desc": "印刷、光刻、增材制造在柔性电极上的应用",
                 "q": "fabrication printing photolithography additive manufacturing flexible electrode process"},
            ],
        },
        {
            "id": "modeling",
            "label": "四、建模与控制",
            "en": "Modeling & Control",
            "level": 3,
            "desc": "从能动到能精确控制，这一层决定它能不能真的用在系统里",
            "children": [
                {"id": "mo_model", "label": "解析模型与等效电路", "en": "Analytical model & equivalent circuit",
                 "level": 3, "cat": None,
                 "desc": "推力-位移-电压的解析表达，参数辨识",
                 "q": "analytical model equivalent circuit identification electrostatic motor simulation thrust model"},
                {"id": "mo_sensing", "label": "位置自感知", "en": "Position self-sensing",
                 "level": 3, "cat": FM,
                 "desc": "不加外部传感器，从驱动电极的电学量反推滑块位置",
                 "q": "position self-sensing sensorless slider detection capacitance charge induction estimation"},
                {"id": "mo_control", "label": "力控制与闭环", "en": "Force control",
                 "level": 3, "cat": None,
                 "desc": "输出力的闭环调节、迟滞与蠕变补偿",
                 "q": "force control closed loop feedback hysteresis creep compensation electrostatic"},
            ],
        },
        {
            "id": "application",
            "label": "五、应用",
            "en": "Applications",
            "level": 2,
            "desc": "这套技术最终用在哪里，以及各自的约束条件",
            "children": [
                {"id": "a_robot", "label": "机器人驱动", "en": "Robotic actuation",
                 "level": 2, "cat": None,
                 "desc": "人工肌肉、软体机器人、仿生驱动",
                 "q": "robot actuator artificial muscle soft robotics bio-inspired electrostatic drive"},
                {"id": "a_climb", "label": "爬壁与攀附", "en": "Wall climbing & perching",
                 "level": 3, "cat": EA,
                 "desc": "电粘附最典型的应用：让机器人贴在墙上、天花板上",
                 "q": "wall climbing robot perching electroadhesion attachment vertical surface ceiling"},
                {"id": "a_haptic", "label": "触觉与可穿戴", "en": "Haptics & wearables",
                 "level": 3, "cat": EA,
                 "desc": "指尖摩擦调制的触觉显示、可穿戴力反馈",
                 "q": "haptic tactile display fingertip friction modulation wearable force feedback"},
                {"id": "a_precision", "label": "精密定位与微操作", "en": "Precision positioning",
                 "level": 3, "cat": FM,
                 "desc": "长行程平面定位、MR 环境等特殊场合（无磁场干扰是静电驱动的独有优势）",
                 "q": "precision positioning long stroke planar stage micromanipulation MRI compatible nonmagnetic"},
            ],
        },
    ],
}


def walk(node: Optional[dict] = None):
    """深度优先遍历所有节点。"""
    node = node or TREE
    yield node
    for ch in node.get("children", []):
        yield from walk(ch)


def leaves() -> list:
    return [n for n in walk() if not n.get("children")]


def find(node_id: str) -> Optional[dict]:
    for n in walk():
        if n["id"] == node_id:
            return n
    return None


def outline() -> str:
    """给大模型看的树形大纲，用来把问题定位到节点。"""
    lines = []
    for top in TREE["children"]:
        lines.append(f"{top['label']}")
        for ch in top.get("children", []):
            lines.append(f"  - {ch['id']}: {ch['label']}（{ch['en']}）{ch['desc']}")
    return "\n".join(lines)


def skeleton() -> dict:
    """去掉查询词的纯结构，给前端画图用。"""
    def strip(n):
        out = {k: v for k, v in n.items() if k != "q"}
        if n.get("children"):
            out["children"] = [strip(c) for c in n["children"]]
        return out
    return strip(TREE)
