package com.acme.legacy.cdi;

import javax.annotation.Priority;
import javax.interceptor.AroundInvoke;
import javax.interceptor.Interceptor;
import javax.interceptor.InvocationContext;

import static javax.interceptor.Interceptor.Priority.APPLICATION;

@Interceptor
@AuditLogged
@Priority(APPLICATION)
public class AuditInterceptor {

    @AroundInvoke
    public Object audit(InvocationContext ctx) throws Exception {
        System.out.println("Invoking: " + ctx.getMethod().getName());
        return ctx.proceed();
    }
}
