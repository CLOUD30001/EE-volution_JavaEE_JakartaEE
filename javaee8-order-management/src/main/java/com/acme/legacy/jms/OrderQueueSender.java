package com.acme.legacy.jms;

import javax.annotation.Resource;
import javax.jms.ConnectionFactory;
import javax.jms.JMSContext;
import javax.jms.JMSProducer;
import javax.jms.Queue;

public class OrderQueueSender {

    @Resource(mappedName = "jms/ConnectionFactory")
    private ConnectionFactory connectionFactory;

    @Resource(mappedName = "jms/OrderQueue")
    private Queue orderQueue;

    public void send(String payload) {
        try (JMSContext context = connectionFactory.createContext()) {
            JMSProducer producer = context.createProducer();
            producer.send(orderQueue, payload);
        }
    }
}
