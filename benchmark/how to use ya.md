# ya

ya is a Python async benchmark framework for measuring the performance of asynchronous functions.

ya 是一个简易的 Python 高性能多进程异步基准测试框架，主要用于压测吞吐量。
因为基于异步，所以可以单机跑出非常高的吞吐量。

## Installation

```bash
uv add --dev https://github.com/Heerozh/ya.git
```

## Usage

```bash
ya <script.py> -n <num_async_tasks> -t <duration_minutes>
```

### Options

- `script.py`: Path to Python script containing benchmark functions
- `-n, --num-tasks`: Number of TOTAL async tasks (light thread), (default: 200)
- `-t, --duration`: Test duration in minutes (default: 5), can be float

## Writing Benchmarks

Create a Python script with async functions that start with `benchmark_`:

```python
import redis.asyncio

# Optional: fixture (if used, runs once per async task before benchmarking)
async def redis_client():
    client = redis.asyncio.Redis(host='localhost', port=6379, db=0)
    yield client
    # Teardown function (runs once per async task after benchmarking)
    # Cleanup code here
    await client.close()

# This function will be benchmarked
async def benchmark_my_function(redis_client):
    # Your async code here
    await redis_client.ping()
```

## How It Works

1. **Discovery**: Ya finds all async functions starting with `benchmark_`
2. **Worker Processes**: Spawns `cpu_core * 2` worker processes using `multiprocessing.Pool.map`
3. **Async Tasks**: Each worker creates `num-tasks//worker` async tasks using `asyncio.gather`
4. **Execution Loop**: Each task:
   - If `benchmark_<name>()` has any parameters, tries to call corresponding fixture functions to get arguments
   - Enters a while loop for `-t` minutes, calling `benchmark_<name>()` each iteration
   - Records [start time, execution time, return value] for each benchmark call
   - Teardown started fixture functions after the loop
5. **Result Collection**: Main process merges all results into a pandas DataFrame
6. **Output**: Displays summary statistics and saves detailed results to `benchmark_results.csv`

## Example

```bash
ya my_benchmark.py -n 200 -t 1
```

## Output

ya 会收集所有基准测试结果并生成统计数据。

Full results are saved to `benchmark_results.csv` with columns:

- `benchmark`: Benchmark function name
- `worker`: Worker process ID
- `timestamp`: Start time when the call started
- `execution_time`: Time taken to execute the benchmark function (in milliseconds)

收集的统计数据为 Statistics：

- CPM (calls per minute), average Throughput (CPS calls per second)
- Mean, k90, k99 response times

注意，CPM/CPS数据，必须目标服务器跑满CPU才正确。

Remember, CPM/CPS data is only accurate if the target server has 100% CPU utilization.

## 输出示例 Output Example

Found 2 benchmark(s): benchmark_cpu_calculation, benchmark_simple_sleep

Running with 24 workers, 8 tasks per worker, for 0.1 minute(s)

Calls Per Minute (CPM) Statistics:

| benchmark                 | execution_time            | execution_count   |
|:--------------------------|:--------------------------|:------------------|
| benchmark_cpu_calculation | 2025-12-05 12:05:00+08:00 | 93,750            |
| benchmark_simple_sleep    | 2025-12-05 12:05:00+08:00 | 69,000            |

Average CPS (Calls Per Second) per Function:

|                           | CPS       |
|:--------------------------|:----------|
| benchmark_cpu_calculation | 12,129.74 |
| benchmark_simple_sleep    | 12,609.60 |

Function Execution Time Statistics:

|                           |   Mean |   k95 |   k99 |   Count |   Min |   Max |   Median |
|:--------------------------|-------:|------:|------:|--------:|------:|------:|---------:|
| benchmark_cpu_calculation |  12.3  | 20.71 | 26.52 |   93750 |  1.11 | 58.84 |    14.49 |
| benchmark_simple_sleep    |  16.72 | 22.06 | 24.31 |   69000 | 10.06 | 48.35 |    15.82 |

Return Value Distribution Statistics:

|    | benchmark                 |   return_value |   count |   percentage |
|---:|:--------------------------|---------------:|--------:|-------------:|
|  3 | benchmark_cpu_calculation |              5 |   36174 |        47.75 |
|  2 | benchmark_cpu_calculation |              4 |   36143 |        47.71 |
|  1 | benchmark_cpu_calculation |              3 |    1721 |         2.27 |
|  4 | benchmark_cpu_calculation |              6 |    1715 |         2.26 |
|  0 | benchmark_cpu_calculation |              2 |       1 |         0    |
|  6 | benchmark_simple_sleep    |              2 |   75592 |       100    |