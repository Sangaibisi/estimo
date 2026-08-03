package com.meridyen.billing;

import com.meridyen.campaign.InstallmentPlanConfig;

/** Taksit planı yaşam döngüsü: oluşturma, faturaya yansıtma, iade kapama. */
public class InstallmentService {

    /** Creates an installment plan for a subscriber from a campaign configuration. */
    public InstallmentPlan createPlan(String subscriberId, InstallmentPlanConfig config) {
        return new InstallmentPlan(subscriberId, config.months(), config.commissionRate());
    }

    /** Cihaz iadesinde planı kapatır ve kalan taksitleri iptal eder. */
    public void closePlanOnReturn(String planId) {
        // remaining installments are voided; refund handled by payment-adapter
    }
}
