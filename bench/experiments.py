"""Your experiments.  *** YOU EXTEND THIS FILE. ***

Run one experiment, or all of them:

    make experiments MEMBER=alice MACHINE=alice-mbp                 # all
    make experiments MEMBER=alice MACHINE=alice-mbp ONLY=example     # one

``example_point_lookups`` below is the summer 2024 interns' one finished experiment, and it works. Copy its
pattern for each experiment the README asks for (E1-E6), and register each
new function in ``EXPERIMENTS`` at the bottom of this file.

The pattern, for every configuration you measure:
    1. prepare keys and queries OUTSIDE the timed region,
    2. build a fresh index (time it with ``time_build`` if build cost matters),
    3. ``index.reset_stats()``, then time one batch with ``time_batch``,
    4. ``writer.record(index, ...)`` one row,
    5. repeat for ``reps`` replicates.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional, Sequence
from bisect import bisect_left, bisect_right
from bench.cli import parse, parser, writer_from_args
from bench.results import ResultsWriter
from bench.timing import build_memory_bytes, time_batch, time_build
from datagen.synthetic import (
    arrange,
    point_queries,
    prefix_queries,
    random_keys,
    range_queries,
)
from indexes import ALL_INDEXES, make_index
from loaders.spotify import key_value_pairs, load_tracks
from indexes.base import PREFIX_UPPER_BOUND

SEED = 4300


def example_point_lookups(writer: ResultsWriter, tracks: list[dict], reps: int) -> None:
    """Build cost and point-lookup (hit) cost on track_id as the index grows."""
    pairs = key_value_pairs(tracks, "track_id")  # file order
    rng = random.Random(SEED)

    for n in (1_000, 10_000, len(pairs)):
        subset = pairs[:n]
        queries = [key for key, _ in rng.sample(subset, 500)]  # every query is a hit

        for name in ALL_INDEXES:
            # Memory once per configuration (tracing is slow; never time it).
            memory = build_memory_bytes(lambda: make_index(name), subset)

            for rep in range(reps):
                common = dict(
                    experiment="example", dataset="spotify", key_column="track_id",
                    insert_order="file", n_keys=n, rep=rep,
                )

                index = make_index(name)
                ns = time_build(index, subset)
                writer.record(
                    index, **common, operation="build", operation_param="",
                    n_ops=n, total_ns=ns, memory_bytes=memory,
                )

                index.reset_stats()
                ns = time_batch(index.search, queries)
                writer.record(
                    index, **common, operation="point_hit", operation_param=1.0,
                    n_ops=len(queries), total_ns=ns,
                    height=index.structure_info().get("height", ""),
                )
            print(f"  n={n:>7,}  {name:<14} done", flush=True)


E2_SIZES = (1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 114_000)
E2_N_QUERIES = 500


def E2_point_lookups(writer: ResultsWriter, tracks: list[dict], reps: int) -> None:
    """Point-lookup cost on track_id as n grows, for hits (rate 1.0) and misses (rate 0.0)."""
    pairs = key_value_pairs(tracks, "track_id")  # file order
    # track_id repeats (a song listed in several genres), so n_keys counts inserted pairs, not distinct ids.

    for n in E2_SIZES:
        subset = pairs[:n]
        keys = [key for key, _ in subset]

        # Generate each query list once per size, before any timer starts.
        # Every index and every replicate sees the same queries.
        queries_by_rate = {
            rate: point_queries(keys, E2_N_QUERIES, rate, seed=SEED + n)
            for rate in (1.0, 0.0)
        }

        for name in ALL_INDEXES:
            for rep in range(reps):
                index = make_index(name)  # fresh index every replicate
                for key, value in subset:  # build is NOT timed here (E1 measures build)
                    index.insert(key, value)

                for rate, queries in queries_by_rate.items():
                    index.reset_stats()  # zero the counters so this batch's counts are its own
                    ns = time_batch(index.search, queries)
                    writer.record(
                        index,
                        experiment="E2_point_lookups", dataset="spotify", key_column="track_id",
                        insert_order="file", n_keys=n,
                        operation="point_hit" if rate == 1.0 else "point_miss",
                        operation_param=rate, n_ops=len(queries), rep=rep, total_ns=ns,
                        height=index.structure_info().get("height", ""),
                    )
            print(f"  E2 n={n:>7,}  {name:<14} done", flush=True)



E1_SIZES = (1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 114_000)


def E1_build_memory(writer: ResultsWriter, tracks: list[dict], reps: int) -> None:
    """Build cost and memory on track_id (file order) as n grows."""
    pairs = key_value_pairs(tracks, "track_id")  # file order

    for n in E1_SIZES:
        subset = pairs[:n]

        for name in ALL_INDEXES:
            # Memory is measured once per configuration; tracing is slow, so it is never timed.
            memory = build_memory_bytes(lambda: make_index(name), subset)

            for rep in range(reps):
                index = make_index(name)  # fresh index every replicate
                ns = time_build(index, subset)
                writer.record(
                    index,
                    experiment="E1_build_memory", dataset="spotify", key_column="track_id",
                    insert_order="file", n_keys=n, operation="build", operation_param="",
                    n_ops=n, rep=rep, total_ns=ns, memory_bytes=memory,
                    height=index.structure_info().get("height", ""),
                )
            print(f"  E1 n={n:>7,}  {name:<14} done", flush=True)


E5_SIZES = (1_000, 10_000, 100_000)
E5_ORDERS = ("random", "sorted", "reversed", "nearly_sorted")
E5_N_QUERIES = 500


def E5_insert_order(writer: ResultsWriter, tracks: list[dict], reps: int) -> None:
    """Does insertion order matter? Synthetic string keys, four arrival orders."""
    for n in E5_SIZES:
        keys = random_keys(n, length=8, seed=SEED + n)
        # The same hit queries for every order, so lookup times are comparable across orders.
        queries = point_queries(keys, E5_N_QUERIES, 1.0, seed=SEED + n)

        for order in E5_ORDERS:
            arranged = arrange(keys, order, seed=SEED + n)
            pairs = [(key, i) for i, key in enumerate(arranged)]

            for name in ALL_INDEXES:
                for rep in range(reps):
                    common = dict(
                        experiment="E5_insert_order", dataset="synthetic",
                        key_column="random_str8", insert_order=order, n_keys=n, rep=rep,
                    )

                    index = make_index(name)  # fresh index every replicate
                    ns = time_build(index, pairs)
                    writer.record(
                        index, **common, operation="build", operation_param="",
                        n_ops=n, total_ns=ns,
                        height=index.structure_info().get("height", ""),
                    )

                    index.reset_stats()
                    ns = time_batch(index.search, queries)
                    writer.record(
                        index, **common, operation="point_hit", operation_param=1.0,
                        n_ops=len(queries), total_ns=ns,
                        height=index.structure_info().get("height", ""),
                    )
                print(f"  E5 n={n:>7,} {order:<13} {name:<14} done", flush=True)


E4_PREFIX_LENGTHS = (1, 2, 3, 4, 5)
E4_N_QUERIES = 500

RANGE_SELECTIVITIES = (0.0001, 0.001, 0.01, 0.05, 0.1, 0.25)
RANGE_N_QUERIES = 200
PREFIX_N_QUERIES = 500
BPLUS_ORDERS = (3, 4, 8, 16, 32, 64, 128, 256, 512)


def _range_workloads(pairs):
    """Prepare the same range workloads for E3 and E6 outside timers."""
    keys = [key for key, _ in pairs]
    sorted_rows = sorted(keys)
    distinct_count = len(set(keys))
    workloads = {}

    for selectivity in RANGE_SELECTIVITIES:
        queries = range_queries(
            keys,
            RANGE_N_QUERIES,
            selectivity,
            seed=SEED,
        )

        mean_rows = sum(
            bisect_right(sorted_rows, hi)
            - bisect_left(sorted_rows, lo)
            for lo, hi in queries
        ) / len(queries)

        notes = (
            f"seed={SEED}; distinct_keys={distinct_count}; "
            f"distinct_keys_per_range="
            f"{max(1, round(selectivity * distinct_count))}; "
            f"mean_rows_returned={mean_rows:.3f}"
        )

        workloads[selectivity] = queries, notes

    return workloads


def E3_range_tempo(
    writer: ResultsWriter,
    tracks: list[dict],
    reps: int,
) -> None:
    """Range-query cost across six tempo selectivities."""
    pairs = key_value_pairs(tracks, "tempo")
    workloads = _range_workloads(pairs)

    for name in ALL_INDEXES:
        for rep in range(reps):
            index = make_index(name)

            for key, value in pairs:
                index.insert(key, value)

            height = index.structure_info().get("height", "")

            for selectivity, (queries, notes) in workloads.items():
                index.reset_stats()

                ns = time_batch(
                    lambda q: index.range_search(*q),
                    queries,
                )

                writer.record(
                    index,
                    experiment="E3_range_tempo",
                    dataset="spotify",
                    key_column="tempo",
                    insert_order="file",
                    n_keys=len(pairs),
                    operation="range",
                    operation_param=selectivity,
                    n_ops=len(queries),
                    rep=rep,
                    total_ns=ns,
                    height=height,
                    notes=notes,
                )

        print(f"  E3 {name:<14} done", flush=True)

def E4_prefix_titles(
    writer: ResultsWriter,
    tracks: list[dict],
    reps: int,
) -> None:
    """Prefix-query cost for title prefix lengths 1 through 5."""
    pairs = key_value_pairs(tracks, "track_name")
    keys = [key for key, _ in pairs]
    sorted_rows = sorted(keys)
    workloads = {}

    for length in range(1, 6):
        queries = prefix_queries(
            keys,
            PREFIX_N_QUERIES,
            length,
            seed=SEED,
        )

        mean_rows = sum(
            bisect_right(sorted_rows, p + PREFIX_UPPER_BOUND)
            - bisect_left(sorted_rows, p)
            for p in queries
        ) / len(queries)

        workloads[length] = (
            queries,
            f"seed={SEED}; mean_rows_returned={mean_rows:.3f}",
        )

    for name in ALL_INDEXES:
        for rep in range(reps):
            index = make_index(name)

            for key, value in pairs:
                index.insert(key, value)

            height = index.structure_info().get("height", "")

            for length, (queries, notes) in workloads.items():
                index.reset_stats()
                ns = time_batch(index.prefix_search, queries)

                writer.record(
                    index,
                    experiment="E4_prefix_titles",
                    dataset="spotify",
                    key_column="track_name",
                    insert_order="file",
                    n_keys=len(pairs),
                    operation="prefix",
                    operation_param=length,
                    n_ops=len(queries),
                    rep=rep,
                    total_ns=ns,
                    height=height,
                    notes=notes,
                )

        print(f"  E4 {name:<14} done", flush=True)

def E4_prefix_track_name(writer: ResultsWriter, tracks: list[dict], reps: int) -> None:
    """Prefix-search cost on track_name (all rows, file order) for prefix lengths 1-5."""
    pairs = key_value_pairs(tracks, "track_name")  # file order; casefolded, the one empty name skipped
    n = len(pairs)
    keys = [key for key, _ in pairs]

    # One query list per prefix length, generated before any timer starts.
    # Every index and every replicate sees the same queries.
    queries_by_length = {
        length: prefix_queries(keys, E4_N_QUERIES, length, seed=SEED + length)
        for length in E4_PREFIX_LENGTHS
    }

    # Short prefixes match far more rows, and every match has to be copied into the
    # result, so record the average result size next to each row (computed untimed,
    # with the C-backed bisect reference, which returns the same answers).
    reference = make_index("ref_bisect")
    for key, value in pairs:
        reference.insert(key, value)
    avg_matches = {
        length: sum(len(reference.prefix_search(q)) for q in queries) / len(queries)
        for length, queries in queries_by_length.items()
    }

    for name in ALL_INDEXES:
        for rep in range(reps):
            index = make_index(name)  # fresh index every replicate
            for key, value in pairs:  # build is NOT timed here (E1 measures build)
                index.insert(key, value)

            for length, queries in queries_by_length.items():
                index.reset_stats()  # zero the counters so this batch's counts are its own
                ns = time_batch(index.prefix_search, queries)
                writer.record(
                    index,
                    experiment="E4_prefix_track_name", dataset="spotify", key_column="track_name",
                    insert_order="file", n_keys=n, operation="prefix", operation_param=length,
                    n_ops=len(queries), rep=rep, total_ns=ns,
                    height=index.structure_info().get("height", ""),
                    notes=f"avg_matches={avg_matches[length]:.1f}",
                )
        print(f"  E4 {name:<14} done", flush=True)

def E6_bplus_order(
    writer: ResultsWriter,
    tracks: list[dict],
    reps: int,
) -> None:
    """Compare nine B+ orders for builds, hits, misses, and ranges."""
    id_pairs = key_value_pairs(tracks, "track_id")
    point_workloads = {}

    for n in E2_SIZES:
        subset = id_pairs[:n]
        keys = [key for key, _ in subset]

        queries_by_rate = {
            rate: point_queries(
                keys,
                E2_N_QUERIES,
                rate,
                seed=SEED + n,
            )
            for rate in (1.0, 0.0)
        }

        point_workloads[n] = subset, queries_by_rate

    tempo_pairs = key_value_pairs(tracks, "tempo")
    ranges, range_notes = _range_workloads(tempo_pairs)[0.01]

    for order in BPLUS_ORDERS:
        for n, (subset, queries_by_rate) in point_workloads.items():
            for rep in range(reps):
                common = dict(
                    experiment="E6_bplus_order",
                    dataset="spotify",
                    key_column="track_id",
                    insert_order="file",
                    n_keys=len(subset),
                    rep=rep,
                    notes=f"seed={SEED + n}",
                )

                index = make_index("bplus_tree", order=order)
                index.reset_stats()

                ns = time_build(index, subset)
                height = index.structure_info()["height"]

                writer.record(
                    index,
                    **common,
                    operation="build",
                    operation_param="",
                    n_ops=len(subset),
                    total_ns=ns,
                    height=height,
                )

                for rate, queries in queries_by_rate.items():
                    index.reset_stats()
                    ns = time_batch(index.search, queries)

                    writer.record(
                        index,
                        **common,
                        operation=(
                            "point_hit" if rate == 1.0 else "point_miss"
                        ),
                        operation_param=rate,
                        n_ops=len(queries),
                        total_ns=ns,
                        height=height,
                    )

        for rep in range(reps):
            index = make_index("bplus_tree", order=order)

            for key, value in tempo_pairs:
                index.insert(key, value)

            height = index.structure_info()["height"]
            index.reset_stats()

            ns = time_batch(
                lambda q: index.range_search(*q),
                ranges,
            )

            writer.record(
                index,
                experiment="E6_bplus_order",
                dataset="spotify",
                key_column="tempo",
                insert_order="file",
                n_keys=len(tempo_pairs),
                operation="range",
                operation_param=0.01,
                n_ops=len(ranges),
                rep=rep,
                total_ns=ns,
                height=height,
                notes=range_notes,
            )

        print(f"  E6 order={order:<3} done", flush=True)


# Register experiments here: name -> function(writer, tracks, reps).

EXPERIMENTS: dict[
    str,
    Callable[[ResultsWriter, list[dict], int], None],
] = {
    "example": example_point_lookups,
    "E1_build_memory": E1_build_memory,
    "E2_point_lookups": E2_point_lookups,
    "E3_range_tempo": E3_range_tempo,
    "E4_prefix_titles": E4_prefix_titles,
    "E5_insert_order": E5_insert_order,
    "E6_bplus_order": E6_bplus_order,
}


def main(argv: Optional[Sequence[str]] = None) -> None:
    p = parser("Run your experiments.")
    p.add_argument("--only", choices=sorted(EXPERIMENTS), help="run just this experiment")
    args = parse(p, argv)
    writer = writer_from_args(args)
    tracks = load_tracks()
    names = [args.only] if args.only else list(EXPERIMENTS)
    for name in names:
        print(f"{name}: {args.reps} reps, session {writer.session_id}", flush=True)
        started = time.perf_counter()
        EXPERIMENTS[name](writer, tracks, args.reps)
        print(f"{name}: finished in {time.perf_counter() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
