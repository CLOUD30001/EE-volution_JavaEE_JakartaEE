package com.acme.legacy.jaxws;

import javax.ejb.Stateless;
import javax.jws.WebMethod;
import javax.jws.WebService;

@Stateless
@WebService(serviceName = "CustomerLookupService")
public class CustomerLookupService {

    @WebMethod
    public String lookupCustomerName(Long customerId) {
        return "Customer-" + customerId;
    }
}
