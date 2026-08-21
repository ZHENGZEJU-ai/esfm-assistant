"""学习路径知识树。两个领域各一棵**完整**的树。

固定骨架 + 动态挂论文：树的结构是按语料里实际有的内容设计的，不由模型现场
生成 —— 模型生成的树每次都不一样，还会编造语料里根本没有的分支，对「学习
路径」这种要求稳定可信的场景是灾难。

为什么两棵树各自写全、而不是共用一套基础层再按领域过滤：
静电力这件事在两个方向上关心的东西根本不同 —— 电机要的是**切向推力**、
行波同步、滑差；吸附要的是**法向吸引**、真实接触面积、Johnsen-Rahbek。
共用一层「静电力基础」再打标签，两边都会读到大量与自己无关的内容。
分开写虽然有重复的主题名，但每个节点的检索词和讲法都是针对性的。

每个节点带 `q`（检索用查询词），提问时把命中的论文挂到对应分支上。
`level` 是建议的学习阶段：1 入门 / 2 进阶 / 3 专题。
"""
from __future__ import annotations

from typing import Iterator, Optional

FM, EA = "film_motor", "electroadhesion"

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

# ---------------------------------------------------------------- 静电吸附
TREE_EA = {
    "id": "ea_root",
    "label": "静电吸附 / 电粘附",
    "en": "Electroadhesion",
    "desc": "用静电力把物体吸住：吸力从哪来、接触面怎么影响它、怎么可控地放开",
    "children": [
        {
            "id": "ea_fund", "label": "一、物理基础", "en": "Fundamentals", "level": 1,
            "desc": "吸附力的来源比看上去复杂 —— 不只是平板电容那套",
            "children": [
                {"id": "ea_force", "label": "静电吸引力与法向应力", "en": "Electrostatic attraction",
                 "level": 1, "desc": "法向吸引力的基本表达；为什么实测值常远高于平板电容模型的预测",
                 "q": "electroadhesion force model normal attraction Maxwell stress parallel plate electrostatic"},
                {"id": "ea_jr", "label": "Johnsen-Rahbek 效应", "en": "Johnsen-Rahbek effect", "level": 1,
                 "desc": "半导电介质让电荷渗到微观接触点，等效间距趋近于零，吸力量级跃升",
                 "q": "Johnsen-Rahbek effect electrostatic chuck semiconductive interface resistivity adhesion"},
                {"id": "ea_dielectric", "label": "介电材料与漏电流", "en": "Dielectric & leakage", "level": 2,
                 "desc": "介电常数、体电阻率、漏电流在吸力与响应速度之间的权衡",
                 "q": "dielectric material permittivity leakage current volume resistivity electroadhesion pad"},
                {"id": "ea_breakdown", "label": "击穿与绝缘设计", "en": "Breakdown & insulation", "level": 2,
                 "desc": "电极间距与介质厚度的取舍：想加高压又不能击穿",
                 "q": "dielectric breakdown insulation thickness high voltage electroadhesive pad design limit"},
            ],
        },
        {
            "id": "ea_mech", "label": "二、吸附机理", "en": "Adhesion mechanisms", "level": 2,
            "desc": "为什么理论算出来的吸力和实测差一个量级 —— 答案在接触界面",
            "children": [
                {"id": "ea_contact", "label": "接触界面与表面粗糙度", "en": "Contact & roughness",
                 "level": 2, "desc": "真实接触面积远小于表观面积，粗糙度直接决定吸力能不能兑现",
                 "q": "surface roughness real contact area asperity interface electroadhesion rough surface"},
                {"id": "ea_shear", "label": "剪切力与法向力的区别", "en": "Shear vs normal", "level": 2,
                 "desc": "两者机理和量级都不同；工程上多数场合真正用到的是剪切保持",
                 "q": "shear force normal force electroadhesion friction holding comparison measurement"},
                {"id": "ea_material", "label": "被吸附材料的影响", "en": "Substrate dependence", "level": 3,
                 "desc": "导体、半导体、绝缘体、生物组织，吸附机理各不相同",
                 "q": "substrate material dependence conductor insulator electroadhesion different surfaces"},
                {"id": "ea_release", "label": "残余吸附与释放", "en": "Residual charge & release",
                 "level": 3, "desc": "断电后电荷不会立刻消失，放不开是实际应用里的常见麻烦",
                 "q": "residual charge release time electroadhesion detachment discharge dynamics"},
            ],
        },
        {
            "id": "ea_dev", "label": "三、器件与工艺", "en": "Devices & fabrication", "level": 2,
            "desc": "电极图形、基底柔性、与其他驱动方式的复合",
            "children": [
                {"id": "ea_pattern", "label": "电极图形设计", "en": "Electrode patterning", "level": 2,
                 "desc": "叉指、螺旋、分区寻址各自的适用场景",
                 "q": "interdigitated electrode spiral pattern design electroadhesive pad geometry optimization"},
                {"id": "ea_pad", "label": "柔性吸附垫", "en": "Flexible adhesion pads", "level": 2,
                 "desc": "柔性基底提高贴合度，直接改善真实接触面积",
                 "q": "flexible electroadhesive pad soft backing conformal contact compliant substrate"},
                {"id": "ea_clutch", "label": "静电离合器", "en": "Electrostatic clutch", "level": 3,
                 "desc": "可控通断的剪切耦合，可穿戴触觉与变刚度结构的核心部件",
                 "q": "electrostatic clutch electroadhesive clutch shear holding wearable variable stiffness"},
                {"id": "ea_hybrid", "label": "与气动/软体复合", "en": "Hybrid with pneumatic", "level": 3,
                 "desc": "静电吸附负责贴附、气动负责变形，两者互补",
                 "q": "hybrid pneumatic electroadhesion soft gripper combined actuation stretchable"},
            ],
        },
        {
            "id": "ea_model", "label": "四、建模与控制", "en": "Modeling & control", "level": 3,
            "desc": "把吸附力做成可预测、可调节的量",
            "children": [
                {"id": "ea_model_force", "label": "吸附力建模", "en": "Force modeling", "level": 3,
                 "desc": "从平板电容到考虑粗糙度和 JR 效应的修正模型",
                 "q": "electroadhesion force model simulation prediction theory rough interface simplified"},
                {"id": "ea_dynamics", "label": "动态响应与控制", "en": "Dynamics & control", "level": 3,
                 "desc": "吸附建立与释放的时间常数，以及闭环调节",
                 "q": "dynamic response time constant control electroadhesion switching modeling DC voltage"},
            ],
        },
        {
            "id": "ea_app", "label": "五、应用", "en": "Applications", "level": 2,
            "desc": "电粘附最有价值的几个落地方向",
            "children": [
                {"id": "ea_climb", "label": "爬壁与攀附", "en": "Wall climbing & perching", "level": 2,
                 "desc": "让机器人贴在墙上、天花板上，是电粘附最典型的应用",
                 "q": "wall climbing robot perching electroadhesion attachment vertical surface ceiling"},
                {"id": "ea_grip", "label": "抓取与操作", "en": "Grasping & manipulation", "level": 2,
                 "desc": "柔性夹持器、薄片搬运、异形件抓取",
                 "q": "electroadhesive gripper grasping manipulation soft robot pick place handling"},
                {"id": "ea_haptic", "label": "触觉与可穿戴", "en": "Haptics & wearables", "level": 3,
                 "desc": "指尖摩擦调制的触觉显示、可穿戴力反馈",
                 "q": "haptic tactile display fingertip friction modulation wearable force feedback electrostatic"},
                {"id": "ea_stiff", "label": "变刚度与结构控制", "en": "Variable stiffness", "level": 3,
                 "desc": "层间可控滑移实现刚度调节，用于可变形结构",
                 "q": "variable stiffness layer jamming electroadhesive laminate programmable structure"},
            ],
        },
    ],
}

TREES = {FM: TREE_FM, EA: TREE_EA}

# 全库视图（/all）用的合并树：两棵树并列，保留完整结构
TREE = {
    "id": "root",
    "label": "静电驱动与静电吸附",
    "en": "Electrostatic Actuation & Adhesion",
    "desc": "两条技术路线：让物体动起来（电机），和让物体粘住（吸附）",
    "children": [TREE_FM, TREE_EA],
}


def get_tree(domain: Optional[str] = None) -> dict:
    """domain 为 film_motor / electroadhesion 时返回对应单树，否则返回合并树。"""
    return TREES.get(domain or "", TREE)


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
