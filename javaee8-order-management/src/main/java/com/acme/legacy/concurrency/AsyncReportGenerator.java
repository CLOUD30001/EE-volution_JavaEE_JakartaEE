package com.acme.legacy.concurrency;

import javax.annotation.Resource;
import javax.enterprise.concurrent.ManagedExecutorService;
import java.util.concurrent.Future;

public class AsyncReportGenerator {

    @Resource
    private ManagedExecutorService executorService;

    public Future<String> generateReportAsync() {
        return executorService.submit(() -> {
            Thread.sleep(100);
            return "report-ready";
        });
    }
}
