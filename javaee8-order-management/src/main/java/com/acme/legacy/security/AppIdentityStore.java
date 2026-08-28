package com.acme.legacy.security;

import javax.enterprise.context.ApplicationScoped;
import javax.security.enterprise.credential.Credential;
import javax.security.enterprise.credential.UsernamePasswordCredential;
import javax.security.enterprise.identitystore.CredentialValidationResult;
import javax.security.enterprise.identitystore.IdentityStore;
import java.util.Collections;

import static javax.security.enterprise.identitystore.CredentialValidationResult.INVALID_RESULT;

@ApplicationScoped
public class AppIdentityStore implements IdentityStore {

    @Override
    public CredentialValidationResult validate(Credential credential) {
        if (credential instanceof UsernamePasswordCredential) {
            UsernamePasswordCredential upc = (UsernamePasswordCredential) credential;
            String password = new String(upc.getPassword().getValue());
            if ("admin".equals(upc.getCaller()) && "changeit".equals(password)) {
                return new CredentialValidationResult(upc.getCaller(), Collections.singleton("ADMIN"));
            }
        }
        return INVALID_RESULT;
    }
}
