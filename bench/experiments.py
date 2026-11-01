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

from bench.cli import parse, parser, writer_from_args
from bench.results import ResultsWriter
from bench.timing import build_memory_bytes, time_batch, time_build
from datagen.synthetic import arrange, point_queries, random_keys
from indexes import ALL_INDEXES, make_index
from loaders.spotify import key_value_pairs, load_tracks

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


# Register experiments here: name -> function(writer, tracks, reps).

EXPERIMENTS: dict[str, Callable[[ResultsWriter, list[dict], int], None]] = {
    "example": example_point_lookups,
    "E1_build_memory": E1_build_memory,
    "E2_point_lookups": E2_point_lookups,
    "E5_insert_order": E5_insert_order,
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
