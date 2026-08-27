#include "thread_pool.h"

#include <algorithm>

namespace refrag {

namespace {

// Background workers are capped by the hardware and by the number of parallel
// render jobs the caller can produce.
int available_threads() {
    unsigned count = std::thread::hardware_concurrency();
    return static_cast<int>(std::max(1u, count));
}

}  // namespace

RenderThreadPool::RenderThreadPool(int max_parallelism) {
    const int total_threads = std::min(available_threads(), std::max(1, max_parallelism));
    const int background_workers = std::max(0, total_threads - 1);
    workers_.reserve(static_cast<std::size_t>(background_workers));
    for (int i = 0; i < background_workers; ++i) {
        workers_.emplace_back([this] { worker_loop(); });
    }
}

RenderThreadPool::~RenderThreadPool() {
    {
        std::lock_guard lock(mutex_);
        stopping_ = true;
        ++generation_;
    }
    start_cv_.notify_all();
    for (auto &worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

void RenderThreadPool::run_jobs() {
    for (;;) {
        std::size_t index = next_.fetch_add(1, std::memory_order_relaxed);
        if (index >= job_count_) {
            return;
        }
        job_(index);
    }
}

void RenderThreadPool::worker_loop() {
    std::size_t observed_generation = 0;
    for (;;) {
        {
            std::unique_lock lock(mutex_);
            start_cv_.wait(lock, [this, observed_generation] {
                return stopping_ || generation_ != observed_generation;
            });
            if (stopping_) {
                return;
            }
            observed_generation = generation_;
        }

        run_jobs();

        {
            std::lock_guard lock(mutex_);
            ++completed_workers_;
            if (completed_workers_ == workers_.size()) {
                done_cv_.notify_one();
            }
        }
    }
}

void RenderThreadPool::parallel_for(
    std::size_t count, const std::function<void(std::size_t)> &job) {
    if (count == 0) {
        return;
    }
    if (workers_.empty() || count == 1) {
        for (std::size_t i = 0; i < count; ++i) {
            job(i);
        }
        return;
    }

    std::lock_guard submit_lock(submit_mutex_);
    {
        std::lock_guard lock(mutex_);
        job_ = job;
        job_count_ = count;
        next_.store(0, std::memory_order_relaxed);
        completed_workers_ = 0;
        ++generation_;
    }
    start_cv_.notify_all();
    run_jobs();

    std::unique_lock lock(mutex_);
    done_cv_.wait(lock, [this] {
        return completed_workers_ == workers_.size();
    });
    job_ = {};
}

}  // namespace refrag
