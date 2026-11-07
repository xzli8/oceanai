# Q1:
## Root Cause
* 'display_name' is dropped while old instances are still running during the rolling deployment, so their reads/writes to 'display_name' will fail.

## Solution: Write both and read switch
1. Add new column 'full_name'
2. Write both 'full_name' and 'display_name' (still read 'display_name')
3. After all old instances are offline, backfill 'full_name' from 'display_name' for all valid data
4. Switch reads to 'full_name' (still write both, so rollback to the original version stays possible)
5. Once stable, write-only 'full_name', and then drop 'display_name'

# Q2:
## Root Cause
* "read database and write cache" is not atomic, all of B's actions could happen between A's read DB and write back to cache.

## Solution: Version + CAS
1. Add a version column to the table, only increase when update. (prevent ABA)
2. When A misses the cache, read both the status and version from the database. Then when updating cache, compare the version firstly, when the version is smaller than the version in cache, drop the update, otherwise execute the update. (These two steps must be atomic and could be implemented by Lua in Redis)
3. When B write to the database, update the status and increase the version by:
'UPDATE table SET status = {status}, version = version + 1 WHERE id = {id}', then write the new status and version to the cache instead of deleting it, return success only after the cache write succeed.

# Q3:
## Chain of failure:
1. Normally, the latency of A calling B is 20ms, 1000 qps * 20ms = 20 busy workers, and A has 50 > 20, so it's fine. 
2. But when latency increase to 2s, each request will hit the timeout limit 100ms and then each retry 3 times, thus we totally have 400ms for each request, 1000qps * 400ms = 400 >> 50, stuck here. (Retrying makes it worse since without retry the total worker needed is 1000qps * 100ms = 100)
3. Unreleated endpoints also stuck since A do not apply bulkhead, all of them share the same thread pool, and the threads in the common pool are all stuck on /report endpoint.

## Solution
1. Bulkhead: each calling of downstream service has their own small thread pool, when the pool is full, reject immediately instead of queueing.
2. Circuit breaker: when the timeout/error rate passes a threshold, open the circuit and fail fast without calling downstream, after a cool-down let a few requests through to check if downstream has recovered.
3. Downgrade: return a cached result or immidately return service unavailable (do not hang on this slow request).
