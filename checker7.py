#!/usr/bin/env python3
import sys
import re


#########################################
# 辅助函数及数据结构定义
#########################################
def to_int(s: str):
    """
    将楼层字符串转换为数值：
      - "B4" -> -4, "B1" -> -1；
      - "F1" -> 0, "F7" -> 6。
    """
    if s[0] == "B":
        try:
            return -int(s[1])
        except:
            return None
    else:
        try:
            return int(s[1:]) - 1
        except:
            return None


class Person:
    def __init__(self, s: str):
        # 格式：[时间戳]乘客ID-PRI-优先级-FROM-起点层-TO-终点层
        i = s.find("]")
        self.send_tick = float(s[1:i].strip())
        args = s[(i + 1):].split("-")
        self.id = int(args[0])
        self.priority = int(args[2])
        self.cur = to_int(args[4])
        self.end = to_int(args[6])
        self.eid = None  # 分配到的电梯编号（0~5），None 表示未分配
        self.arrive_tick = 0.0

    def __hash__(self):
        return self.id.__hash__()

    def __eq__(self, other):
        return self.id == other.id

    def __str__(self):
        return f"Person {self.id}"


class Elevator:
    def __init__(self, eid: int):
        # eid: 0~5，对应电梯编号1~6
        self.eid = eid
        self.floor = 0
        self.top = 6
        self.base = -4
        self.is_close = True
        self.peoples = set()  # 轿厢内乘客
        self.received = set()  # 当前 RECEIVE 分配（乘客 id 集合）
        self.last_action = None  # 上一次有效动作类型（如 ARRIVE, CLOSE, …）
        self.last_action_tick = 0.0

        # SCHE 相关：仅在正式状态（on_sche）时要求特殊检查，
        # 在收到 SCHE-ACCEPT时仅设置 pre_sche=True，并开始累计 ARRIVE 次数（不严格要求门间隔等）
        self.pre_sche = False  # 收到 SCHE-ACCEPT后，尚未进入正式 SCHE 状态
        self.on_sche = False  # 正式 SCHE 状态（SCHE-BEGIN到SCHE-END期间）
        self.on_sche_speed = 0.4  # SCHE 时最小移动时间（s/层）
        self.sche_target = None  # SCHE目标楼层（int）
        self.got_sche_tick = 0.0  # SCHE-ACCEPT 时间戳
        self.sche_arrive_count = 0  # 仅在 pre_sche 状态下累计 ARRIVE 次数（≤2）

        # UPDATE 相关：同理，预状态与正式状态分开
        self.pre_update = False
        self.on_update = False
        self.partner = None  # 搭档电梯编号（0~5）
        self.update_target = None
        self.got_update_tick = 0.0  # UPDATE-ACCEPT 时间戳
        self.update_arrive_count = 0  # 仅在 pre_update 状态下累计 ARRIVE 次数（≤2）
        self.update_begin_tick = 0.0  # 记录 UPDATE-BEGIN 时间

        # 改造完成后状态（特殊状态结束后）
        self.after_update = False
        self.movement_bounds = None  # UPDATE后运行范围

    def reset_sche(self):
        # 清除 SCHE 相关标志
        self.on_sche = False
        self.pre_sche = False
        self.sche_target = None
        self.got_sche_tick = 0.0
        self.sche_arrive_count = 0
        self.on_sche_speed = 0.4
        # 同时清空该电梯 RECEIVE（全局记录将在外部同步清除）

    def reset_update(self):
        self.on_update = False
        self.pre_update = False
        self.got_update_tick = 0.0
        self.update_arrive_count = 0
        self.update_begin_tick = 0.0


#########################################
# 辅助：清除全局 RECEIVE 中分配给某电梯的记录
#########################################
def clear_global_receive(eid):
    remove_ids = [pid for pid, rid in receive_assign.items() if rid == eid]
    for pid in remove_ids:
        del receive_assign[pid]


#########################################
# 全局状态及文件输入
#########################################
elevators = [Elevator(i) for i in range(6)]
persons = {}
stdin_lines = []
try:
    with open("stdin.txt", "r") as f:
        stdin_lines = f.readlines()
except Exception as e:
    print("读取stdin.txt失败:", e)
    sys.exit(1)

for line in stdin_lines:
    line = line.strip()
    if not line:
        continue
    if "SCHE" in line or "UPDATE" in line:
        continue
    try:
        p = Person(line)
        if p.id in persons:
            raise RuntimeError(f"重复的乘客请求：{p.id}")
        persons[p.id] = p
    except Exception as e:
        print("解析乘客请求失败:", e)
        sys.exit(1)

# 全局 RECEIVE 记录：pid -> elevator id
receive_assign = {}

watt = 0.0
last_output_tick = 0.0
error_count = 0


def error(msg, tick=None, line=None):
    global error_count
    error_count += 1
    tstr = f" [ts={tick}]" if tick is not None else ""
    lstr = f" [line: {line}]" if line is not None else ""
    raise RuntimeError(f"错误: {msg}{tstr}{lstr}")


#########################################
# 处理 stdout.txt 输出日志
#########################################
try:
    with open("stdout.txt", "r") as f:
        stdout_lines = f.readlines()
except Exception as e:
    print("读取stdout.txt失败:", e)
    sys.exit(1)

for line in stdout_lines:
    data = line.strip()
    if not data:
        continue
    m = re.match(r'\[\s*([\d\.]+)\](.*)', data)
    if not m:
        error("无法解析时间戳", line=data)
        continue
    tick = float(m.group(1).strip())
    if tick < last_output_tick:
        error(f"时间戳不递增：{tick} < {last_output_tick}", tick, data)
    last_output_tick = tick
    content = m.group(2).strip()
    args = content.split("-")
    cmd = args[0]

    # 对于非 SCHE/UPDATE/RECEIVE/IN/OUT 命令（即 ARRIVE, OPEN, CLOSE），采用最后两个参数解析：楼层、 电梯编号
    if cmd not in ("SCHE", "UPDATE", "RECEIVE", "IN", "OUT"):
        if len(args) < 3:
            error("输出格式错误，不足参数", tick, data)
            continue
        fl = to_int(args[-2])
        try:
            eid = int(args[-1]) - 1
        except:
            error("输出中电梯编号格式错误", tick, data)
            continue
        if eid < 0 or eid >= len(elevators):
            error("电梯编号超界", tick, data)
            continue
        elev = elevators[eid]
    # 以下各分支分别处理各命令
    # ------ ARRIVE ------
    if cmd == "ARRIVE":
        if fl is None:
            error("无法解析 ARRIVE 楼层", tick, data)
            continue
        if abs(fl - elev.floor) != 1:
            error(f"电梯 {eid + 1} 移动超过一层，从 {elev.floor} 到 {fl}", tick, data)
        if not elev.is_close:
            error(f"电梯 {eid + 1} 在门开状态下移动", tick, data)
        # 仅在普通状态下检查空载：若电梯既无乘客又无 RECEIVE 且不处于预状态和特殊状态，则报错
        if (not (elev.pre_sche or elev.on_sche or elev.pre_update or elev.on_update or elev.after_update)) and (
                len(elev.peoples) == 0 and len(elev.received) == 0):
            error(f"电梯 {eid + 1} 为空且无 RECEIVE 却移动", tick, data)
        # 仅在预状态（pre_sche, pre_update）下累计 ARRIVE 次数
        if elev.pre_sche:
            elev.sche_arrive_count += 1
            if elev.sche_arrive_count > 2:
                error(f"电梯 {eid + 1} SCHE 预状态下 ARRIVE 次数超过2", tick, data)
        if elev.pre_update:
            elev.update_arrive_count += 1
            if elev.update_arrive_count > 2:
                error(f"电梯 {eid + 1} UPDATE 预状态下 ARRIVE 次数超过2", tick, data)
        if elev.last_action in ("CLOSE", "ARRIVE"):
            dt = tick - elev.last_action_tick
            if elev.on_sche:
                exp_speed = elev.on_sche_speed
            elif elev.on_update or elev.after_update:
                exp_speed = 0.2
            else:
                exp_speed = 0.4
            if dt < exp_speed - 0.01:
                error(f"电梯 {eid + 1} 移动时间 {dt:.3f}s 小于最小要求 {exp_speed}s", tick, data)
        elev.last_action = "ARRIVE"
        elev.last_action_tick = tick
        elev.floor = fl
        if elev.after_update and elev.partner is not None:
            partner = elevators[elev.partner]
            if partner.after_update:
                if elev.floor == partner.floor:
                    error(f"双轿厢冲突：电梯 {eid + 1} 与 {partner.eid + 1} 同层 {elev.floor}", tick, data)
        if fl > elev.top or fl < elev.base :
            error(f"电梯 {eid + 1} 越界", tick, data)
        if elev.on_update or elev.after_update:
            watt += 0.2
        else:
            watt += 0.4

    # ------ OPEN ------
    elif cmd == "OPEN":
        if fl is None:
            error("无法解析 OPEN 楼层", tick, data)
            continue
        if elev.floor != fl:
            error(f"电梯 {eid + 1} OPEN 楼层不符：实际 {elev.floor} 要求 {fl}", tick, data)
            continue
        # 如果处于正式特殊状态 (on_sche 或 on_update 且 not after_update)，OPEN 只允许在目标楼层
        if ((elev.on_sche or elev.on_update) and (not elev.after_update)):
            target = elev.sche_target if elev.on_sche else elev.update_target
            if fl != target:
                error(f"电梯 {eid + 1} 在特殊状态下非目标楼层 OPEN", tick, data)
        elev.last_action = "OPEN"
        elev.last_action_tick = tick
        elev.last_open_tick = tick
        elev.is_close = False
        watt += 0.1

    # ------ CLOSE ------
    elif cmd == "CLOSE":
        if elev.floor != fl:
            error(f"电梯 {eid + 1} CLOSE 楼层不符：实际 {elev.floor} 要求 {fl}", tick, data)
        if elev.is_close:
            error(f"电梯 {eid + 1} 重复关门", tick, data)
        if elev.last_open_tick > 0:
            duration = tick - elev.last_open_tick
            if ((elev.on_sche or elev.on_update) and (not elev.after_update)):
                req = 1.0
            else:
                req = 0.4
            if duration < req - 0.0001:
                error(f"电梯 {eid + 1} 开关门间隔 {duration:.3f}s 小于要求 {req}s", tick, data)
        elev.last_action = "CLOSE"
        elev.last_action_tick = tick
        elev.last_close_tick = tick
        elev.is_close = True
        watt += 0.1

    # ------ RECEIVE ------
    elif cmd == "RECEIVE":
        if len(args) < 3:
            error("RECEIVE 格式错误", tick, data)
            continue
        try:
            pid = int(args[1])
            rid = int(args[2]) - 1
        except:
            error("RECEIVE 中数字格式错误", tick, data)
            continue
        # 若处于正式特殊状态（on_sche 或 on_update）则禁止 RECEIVE；预状态或结束后允许
        if ((elevators[rid].on_sche or elevators[rid].on_update) and (not elevators[rid].after_update)):
            error(f"电梯 {rid + 1} 在特殊状态下不允许 RECEIVE", tick, data)
        else:
            if pid in receive_assign:
                error(f"乘客 {pid} 已分配给电梯 {receive_assign[pid] + 1}，重复 RECEIVE", tick, data)
            else:
                receive_assign[pid] = rid
                elevators[rid].received.add(pid)
        elevators[rid].last_action = "RECEIVE"
        elevators[rid].last_action_tick = tick

    # ------ IN ------
    elif cmd == "IN":
        if len(args) < 4:
            error("IN 格式错误", tick, data)
            continue
        try:
            pid = int(args[1])
            fl = to_int(args[2])
            rid = int(args[3]) - 1
        except:
            error("IN 中数字格式错误", tick, data)
            continue
        if pid not in persons:
            error(f"IN 出现未知乘客: {pid}", tick, data)
            continue
        if elevators[rid].is_close:
            error(f"电梯 {rid + 1} 门关闭状态下 IN", tick, data)
        if elevators[rid].floor != fl:
            error(f"电梯 {rid + 1} IN 楼层错误：实际 {elevators[rid].floor} 要求 {fl}", tick, data)
        if receive_assign.get(pid) != rid:
            error(f"乘客 {pid} 未被分配给电梯 {rid + 1}，无法 IN", tick, data)
        if pid in elevators[rid].received:
            elevators[rid].received.remove(pid)
        p = persons[pid]
        p.eid = rid
        elevators[rid].peoples.add(p)
        if len(elevators[rid].peoples) > 6:
            error(f"电梯 {rid + 1} 超载：人数 {len(elevators[rid].peoples)}", tick, data)
        elevators[rid].last_action = "IN"
        elevators[rid].last_action_tick = tick

    # ------ OUT ------
    elif cmd == "OUT":
        m_out = re.match(r'OUT-([SF])-(\d+)-(\S+)-(\d+)', content)
        if not m_out:
            error("OUT 格式错误", tick, data)
            continue
        outcome = m_out.group(1)
        try:
            pid = int(m_out.group(2))
        except:
            error("OUT 中乘客ID格式错误", tick, data)
            continue
        fl = to_int(m_out.group(3))
        try:
            rid = int(m_out.group(4)) - 1
        except:
            error("OUT 中电梯ID格式错误", tick, data)
            continue
        if pid not in persons:
            error(f"OUT 出现未知乘客：{pid}", tick, data)
            continue
        p = persons[pid]
        if elevators[rid].is_close:
            error(f"电梯 {rid + 1} OUT 时门关闭", tick, data)
        if elevators[rid].floor != fl:
            error(f"电梯 {rid + 1} OUT 楼层错误：实际 {elevators[rid].floor} 要求 {fl}", tick, data)
        if p not in elevators[rid].peoples:
            error(f"乘客 {pid} 不在电梯 {rid + 1} 内，无法 OUT", tick, data)
        if outcome == "S":
            if fl != p.end:
                error(f"乘客 {pid} 标记到达，但楼层 {fl} 与目标 {p.end} 不符", tick, data)
            p.arrive_tick = tick
        else:
            if fl == p.end:
                error(f"乘客 {pid} 到达目标却输出 OUT-F", tick, data)
        elevators[rid].peoples.remove(p)
        if pid in receive_assign:
            del receive_assign[pid]
        p.cur = elevators[rid].floor
        p.eid = None
        elevators[rid].last_action = "OUT"
        elevators[rid].last_action_tick = tick

    # ------ SCHE ------
    elif cmd == "SCHE":
        if len(args) < 2:
            error("SCHE 格式错误", tick, data)
            continue
        subtype = args[1]
        if subtype == "ACCEPT":
            # 格式：SCHE-ACCEPT-电梯ID-临时运行速度-目标楼层
            if len(args) < 5:
                error("SCHE-ACCEPT 格式错误", tick, data)
                continue
            try:
                rid = int(args[2]) - 1
                spd = float(args[3])
            except:
                error("SCHE-ACCEPT 数字字段错误", tick, data)
                continue
            target_floor = to_int(args[4])
            elev = elevators[rid]
            elev.pre_sche = True
            elev.on_sche_speed = spd
            elev.sche_target = target_floor
            elev.got_sche_tick = tick
            elev.sche_arrive_count = 0
            elev.last_action = "SCHE-ACCEPT"
            elev.last_action_tick = tick
        elif subtype == "BEGIN":
            # 格式：SCHE-BEGIN-电梯ID
            if len(args) < 3:
                error("SCHE-BEGIN 格式错误", tick, data)
                continue
            try:
                rid = int(args[2]) - 1
            except:
                error("SCHE-BEGIN 电梯ID格式错误", tick, data)
                continue
            elev = elevators[rid]
            if not elev.pre_sche:
                error(f"电梯 {rid + 1} 未收到 SCHE-ACCEPT却输出 SCHE-BEGIN", tick, data)
            if not elev.is_close:
                error(f"电梯 {rid + 1} SCHE-BEGIN 时门未关闭", tick, data)
            elev.on_sche = True
            elev.pre_sche = False
            elev.last_action = "SCHE-BEGIN"
            elev.last_action_tick = tick
            elev.received.clear()
            clear_global_receive(rid)
        elif subtype == "END":
            # 格式：SCHE-END-电梯ID
            if len(args) < 3:
                error("SCHE-END 格式错误", tick, data)
                continue
            try:
                rid = int(args[2]) - 1
            except:
                error("SCHE-END 电梯ID格式错误", tick, data)
                continue
            elev = elevators[rid]
            if not elev.on_sche:
                error(f"电梯 {rid + 1} 未处于 SCHE 状态却输出 SCHE-END", tick, data)
            if tick - elev.got_sche_tick > 6.0001:
                error(f"电梯 {rid + 1} SCHE 响应时间 {tick - elev.got_sche_tick:.3f}s 超过6s", tick, data)
            if elev.peoples:
                error(f"电梯 {rid + 1} SCHE-END 时轿厢不为空", tick, data)
            if not elev.is_close:
                error(f"电梯 {rid + 1} SCHE-END 时门未关闭", tick, data)
            elev.reset_sche()  # 清除所有 SCHE 相关状态
            clear_global_receive(rid)
            elev.last_action = "SCHE-END"
            elev.last_action_tick = tick

    # ------ UPDATE ------
    elif cmd == "UPDATE":
        if len(args) < 2:
            error("UPDATE 格式错误", tick, data)
            continue
        subtype = args[1]
        if subtype == "ACCEPT":
            # 格式：UPDATE-ACCEPT-A电梯ID-B电梯ID-目标楼层
            if len(args) < 5:
                error("UPDATE-ACCEPT 格式错误", tick, data)
                continue
            try:
                aid = int(args[2]) - 1
                bid = int(args[3]) - 1
            except:
                error("UPDATE-ACCEPT 电梯ID格式错误", tick, data)
                continue
            target_floor = to_int(args[4])
            elevA = elevators[aid]
            elevB = elevators[bid]
            elevA.pre_update = True
            elevB.pre_update = True
            elevA.partner = bid
            elevB.partner = aid
            elevA.update_target = target_floor
            elevB.update_target = target_floor
            elevA.got_update_tick = tick
            elevB.got_update_tick = tick
            elevA.update_arrive_count = 0
            elevB.update_arrive_count = 0
            elevA.last_action = "UPDATE-ACCEPT"
            elevA.last_action_tick = tick
            elevB.last_action = "UPDATE-ACCEPT"
            elevB.last_action_tick = tick
        elif subtype == "BEGIN":
            # 格式：UPDATE-BEGIN-A电梯ID-B电梯ID
            if len(args) < 4:
                error("UPDATE-BEGIN 格式错误", tick, data)
                continue
            try:
                aid = int(args[2]) - 1
                bid = int(args[3]) - 1
            except:
                error("UPDATE-BEGIN 电梯ID格式错误", tick, data)
                continue
            elevA = elevators[aid]
            elevB = elevators[bid]
            if not (elevA.is_close and elevB.is_close):
                error(f"UPDATE-BEGIN 时电梯 {aid + 1} 或 {bid + 1} 门未关闭", tick, data)
            if elevA.peoples or elevB.peoples:
                error(f"UPDATE-BEGIN 时电梯 {aid + 1} 或 {bid + 1} 轿厢不为空", tick, data)
            if elevA.update_arrive_count > 2 or elevB.update_arrive_count > 2:
                error(f"UPDATE-BEGIN 前，电梯 {aid + 1} 或 {bid + 1} ARRIVE 次数超过2", tick, data)
            elevA.on_update = True
            elevB.on_update = True
            elevA.base = elevA.update_target
            elevB.top = elevB.update_target
            elevA.pre_update = False
            elevB.pre_update = False
            elevA.update_begin_tick = tick
            elevB.update_begin_tick = tick
            elevA.last_action = "UPDATE-BEGIN"
            elevA.last_action_tick = tick
            elevB.last_action = "UPDATE-BEGIN"
            elevB.last_action_tick = tick
            elevA.received.clear()
            elevB.received.clear()
            clear_global_receive(aid)
            clear_global_receive(bid)
        elif subtype == "END":
            # 格式：UPDATE-END-A电梯ID-B电梯ID
            if len(args) < 4:
                error("UPDATE-END 格式错误", tick, data)
                continue
            try:
                aid = int(args[2]) - 1
                bid = int(args[3]) - 1
            except:
                error("UPDATE-END 电梯ID格式错误", tick, data)
                continue
            elevA = elevators[aid]
            elevB = elevators[bid]
            if tick - elevA.got_update_tick > 6.0001 or tick - elevB.got_update_tick > 6.0001:
                error(f"UPDATE 响应时间超过6s：电梯 {aid + 1} 或 {bid + 1}", tick, data)
            if not (elevA.is_close and elevB.is_close):
                error(f"UPDATE-END 时电梯 {aid + 1} 或 {bid + 1} 门未关闭", tick, data)
            if elevA.peoples or elevB.peoples:
                error(f"UPDATE-END 时电梯 {aid + 1} 或 {bid + 1} 轿厢不为空", tick, data)
            if elevA.on_update:
                if tick - elevA.update_begin_tick < 1.0 - 0.0001:
                    error(f"UPDATE 改造过程时间不足 1s：电梯 {aid + 1} 或 {bid + 1}", tick, data)
            else:
                error(f"未输出 UPDATE-BEGIN 却收到 UPDATE-END：电梯 {aid + 1} 或 {bid + 1}", tick, data)
            elevA.floor = elevA.update_target + 1
            elevB.floor = elevB.update_target - 1
            elevA.after_update = True
            elevB.after_update = True
            elevA.reset_update()
            elevB.reset_update()
            clear_global_receive(aid)
            clear_global_receive(bid)
            elevA.last_action = "UPDATE-END"
            elevA.last_action_tick = tick
            elevB.last_action = "UPDATE-END"
            elevB.last_action_tick = tick

    else:
        error(f"未知输出命令: {cmd}", tick, data)

#########################################
# 双轿厢冲突检测（改造后状态下）
#########################################
for elev in elevators:
    if elev.after_update and elev.partner is not None:
        partner = elevators[elev.partner]
        if partner.after_update:
            if elev.floor == partner.floor:
                error(f"双轿厢冲突：电梯 {elev.eid + 1} 与 {partner.eid + 1} 同层 {elev.floor}")

#########################################
# 检查所有电梯最终状态
#########################################
for elev in elevators:
    if not elev.is_close:
        error(f"电梯 {elev.eid + 1} 结束时门未关闭")
    if elev.peoples:
        error(f"电梯 {elev.eid + 1} 结束时轿厢内仍有乘客")
    if elev.received:
        error(f"电梯 {elev.eid + 1} 结束时仍有未处理的 RECEIVE")
    if elev.on_sche:
        error(f"电梯 {elev.eid + 1} 处于未完成的 SCHE 状态")
    if elev.on_update:
        error(f"电梯 {elev.eid + 1} 处于未完成的 UPDATE 状态")

#########################################
# 检查所有乘客是否到达目的地
#########################################
for pid, p in persons.items():
    if p.cur != p.end:
        error(f"乘客 {pid} 未到达目的地：当前 {p.cur} 目标 {p.end}")

#########################################
# 输出统计信息
#########################################
total_time = last_output_tick
total_priority = sum(p.priority for p in persons.values())
weighted_wait = sum(p.priority * (p.arrive_tick - p.send_tick) for p in persons.values())
avg_wait = weighted_wait / total_priority if total_priority > 0 else 0.0

if error_count == 0:
    print(f"Accepted\t运行时间: {total_time:.1f}s\t等待时间: {avg_wait:.3f}s\t耗电量: {watt:.1f}")
else:
    print(f"检测到 {error_count} 个错误，请检查输出日志。")
