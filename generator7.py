import argparse
import random
import math


def parse_args():
    parser = argparse.ArgumentParser(description="生成电梯系统输入数据")
    # 请求数量参数
    parser.add_argument('--num_regular_requests', type=int, default=100,
                        help="普通乘客请求数量")
    parser.add_argument('--num_updates', type=int, default=3,
                        help="UPDATE（双轿厢改造）请求数量，每个请求涉及一对电梯")
    # 时间范围参数（单位：秒）
    parser.add_argument('--time_range', type=float, nargs=2, default=[0.0, 50.0],
                        help="普通乘客请求的时间范围")
    # SCHE 请求时间范围（生成密集数据，尽量与普通请求分布在一起）
    parser.add_argument('--sche_time_range', type=float, nargs=2, default=[5.0, 60.0],
                        help="SCHE 请求的时间范围")
    parser.add_argument('--update_time_range', type=float, nargs=2, default=[20.0, 61.0],
                        help="UPDATE 请求的时间范围")
    # 其他参数
    parser.add_argument('--elevator_ids', type=int, nargs='+', default=[1, 2, 3, 4, 5, 6],
                        help="电梯 ID 列表")
    parser.add_argument('--max_concurrent', type=int, default=5,
                        help="最大并发请求数")
    return parser.parse_args()


def gen_timestamps(n, time_range):
    """生成 n 个在 time_range 内的随机时间戳，保留一位小数，排序后返回列表"""
    start, end = time_range
    ts = [round(random.uniform(start, end), 1) for _ in range(n)]
    ts.sort()
    return ts


def generate_regular_requests(num, time_range):
    """
    生成普通乘客请求：
    格式: [时间戳]乘客ID-PRI-优先级指数-FROM-起点层-TO-终点层
    可到达楼层：地下 B4, B3, B2, B1 与 地上 F1-F7（共11层），起点与终点必须不同
    """
    floors = ["B4", "B3", "B2", "B1", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    timestamps = gen_timestamps(num, time_range)
    events = []
    for i in range(num):
        passenger_id = i + 1
        priority = random.randint(1, 100)
        from_floor, to_floor = random.sample(floors, 2)
        event = f"[{timestamps[i]}]{passenger_id}-PRI-{priority}-FROM-{from_floor}-TO-{to_floor}"
        events.append((timestamps[i], event))
    return events


def generate_update_requests(num, update_time_range, elevator_ids):
    """
    生成 UPDATE 请求（双轿厢改造），格式为:
      [时间戳]UPDATE-ida-idb-floor
    要求：
      - 每个 UPDATE 请求涉及一对电梯 ida 和 idb，且两者不能重复出现（即每部电梯最多更新一次）
    返回:
      - events: UPDATE 请求事件列表
      - update_info: 字典，记录所有被 UPDATE 的电梯的 id 及其 UPDATE 请求时间
    """
    allowed_floors = ["B2", "B1", "F1", "F2", "F3", "F4", "F5"]
    # 为了保证两两配对，最大更新请求数不能超过 floor(len(elevator_ids)/2)
    max_updates = len(elevator_ids) // 2
    if num > max_updates:
        raise ValueError(f"UPDATE 请求数不能超过 {max_updates}（电梯总数的二分之一）")

    timestamps = gen_timestamps(num, update_time_range)
    events = []
    update_info = {}

    # 从所有电梯中随机选出 2*num 个电梯，然后将它们两两配对
    selected_ids = random.sample(elevator_ids, 2 * num)
    for i in range(num):
        a = selected_ids[2 * i]
        b = selected_ids[2 * i + 1]
        target_floor = random.choice(allowed_floors)
        t = timestamps[i]
        event = f"[{t}]UPDATE-{a}-{b}-{target_floor}"
        events.append((t, event))
        # 记录 a 和 b 的 UPDATE 时间
        update_info[a] = t
        update_info[b] = t
    return events, update_info


def generate_sche_requests_dense(sche_time_range, elevator_ids, update_info):
    """
    密集生成 SCHE 请求（临时调度），格式为:
      [时间戳]SCHE-电梯ID-临时运行速度-目标楼层
    限定目标楼层：B2, B1, F1, F2, F3, F4, F5
    临时运行速度可取：0.2, 0.3, 0.4, 0.5
    要求：
      - 对于同一部电梯，SCHE 请求间隔至少 6 秒；
      - 如果电梯在 update_info 中，则允许 SCHE 请求的时间上限为 (update_time - 8)；
      - 对于不在 update_info 中的电梯，上限为 sche_time_range[1]。
    对每部电梯生成密集的 SCHE 请求序列。
    返回所有 SCHE 请求事件列表。
    """
    allowed_floors = ["B2", "B1", "F1", "F2", "F3", "F4", "F5"]
    speeds = [0.2, 0.3, 0.4, 0.5]
    sche_min, sche_max = sche_time_range
    events = []
    for eid in elevator_ids:
        # 对于每部电梯，确定 SCHE 请求允许的上界：
        if eid in update_info:
            # 此电梯更新后不允许出现 SCHE 请求，允许上界为 update_time - 8
            allowed_upper = update_info[eid] - 8.0
        else:
            allowed_upper = sche_max

        # 如果允许上界低于 sche_min，则该电梯不生成 SCHE 请求
        if allowed_upper < sche_min:
            continue

        # 为密集生成，令该电梯的第一个 SCHE 时间在 [sche_min, sche_min+0.5]
        t = round(random.uniform(sche_min, sche_min + 0.5), 1)
        while t <= allowed_upper:
            if random.random() < 0.75 :
                event = f"[{t}]SCHE-{eid}-{random.choice(speeds)}-{random.choice(allowed_floors)}"
                events.append((t, event))
            t = round(t + 6.0, 1)
    events.sort(key=lambda x: x[0])
    return events


def main():
    args = parse_args()

    # 生成普通乘客请求，时间范围 [0,70] 秒
    regular_events = generate_regular_requests(args.num_regular_requests, args.time_range)

    # 生成 UPDATE 请求及记录 update_info（时间范围 [10,60] 秒）
    update_events, update_info = generate_update_requests(args.num_updates, args.update_time_range, args.elevator_ids)

    # 密集生成 SCHE 请求：对所有电梯生成，
    # 若电梯被 UPDATE，则 SCHE 请求上限为 (update_time - 8)；否则上限为 sche_time_range[1]
    sche_events = generate_sche_requests_dense(args.sche_time_range, args.elevator_ids, update_info)

    # 合并所有事件（普通请求、SCHE、UPDATE），按时间戳排序（非减）
    all_events = regular_events + sche_events + update_events
    all_events.sort(key=lambda x: x[0])

    # 写入文件 stdin.txt
    with open("stdin.txt", "w", encoding="utf-8") as f:
        for (_, event) in all_events:
            f.write(event + "\n")


if __name__ == "__main__":
    main()
