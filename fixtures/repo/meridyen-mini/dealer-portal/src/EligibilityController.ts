import { InstallmentEligibilityService } from "./InstallmentEligibilityService";

/** Bayi satış anında abonenin taksitlendirme uygunluğunu sorgular. */
export class EligibilityController {
  constructor(private readonly service: InstallmentEligibilityService) {}

  /** Checks dealer-side installment eligibility for a subscriber. */
  async checkInstallmentEligibility(subscriberId: string): Promise<boolean> {
    return this.service.isEligible(subscriberId);
  }
}
