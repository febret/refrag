#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

namespace refrag {

class RenderThreadPool {
  public:
    explicit RenderThreadPool(int max_parallelism);
    ~RenderThreadPool();

    RenderThreadPool(const RenderThreadPool &) = delete;
    RenderThreadPool &operator=(const RenderThreadPool &) = delete;

    void parallel_for(std::size_t count, const std::function<void(std::size_t)> &job);

  private:
    void worker_loop();
    void run_jobs();

    std::vector<std::thread> workers_;
    std::mutex mutex_;
    std::mutex submit_mutex_;
    std::condition_variable start_cv_;
    std::condition_variable done_cv_;
    std::function<void(std::size_t)> job_;
    std::atomic<std::size_t> next_{0};
    std::size_t job_count_ = 0;
    std::size_t generation_ = 0;
    std::size_t completed_workers_ = 0;
    bool stopping_ = false;
};

}  // namespace refrag
