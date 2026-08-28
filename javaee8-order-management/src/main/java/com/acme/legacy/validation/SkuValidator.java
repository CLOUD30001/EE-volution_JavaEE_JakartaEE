package com.acme.legacy.validation;

import javax.validation.ConstraintValidator;
import javax.validation.ConstraintValidatorContext;

public class SkuValidator implements ConstraintValidator<ValidSku, String> {

    @Override
    public boolean isValid(String value, ConstraintValidatorContext context) {
        return value != null && value.matches("^[A-Z]{3}-\\d{4,6}$");
    }
}
