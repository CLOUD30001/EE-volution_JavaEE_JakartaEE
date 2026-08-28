package com.acme.legacy.xml;

import com.acme.legacy.entity.Customer;

import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Marshaller;
import java.io.StringWriter;

/**
 * JAXB was removed from the JDK starting with Java 11 (not merely renamed) and
 * additionally moves to the jakarta.xml.bind package under Jakarta EE 9+.
 */
public class CustomerXmlMapper {

    public String toXml(Customer customer) throws JAXBException {
        JAXBContext context = JAXBContext.newInstance(Customer.class);
        Marshaller marshaller = context.createMarshaller();
        StringWriter writer = new StringWriter();
        marshaller.marshal(customer, writer);
        return writer.toString();
    }
}
