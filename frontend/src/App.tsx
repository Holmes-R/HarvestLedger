import type { ReactNode } from "react";

import { AppShell } from "./components/AppShell";
import { DeliveryDetail } from "./components/DeliveryDetail";
import { navigate, useHashRoute } from "./hooks/useHashRoute";
import { DeliveriesScreen } from "./screens/DeliveriesScreen";
import { LedgerScreen } from "./screens/LedgerScreen";
import { PayoutDetail, PayoutsScreen } from "./screens/PayoutsScreen";
import { PricesScreen } from "./screens/PricesScreen";
import { ledgerBackTarget } from "./util/ledger";
import "./App.css";

const SECTIONS = new Set(["deliveries", "prices", "payouts", "ledger"]);

function App() {
  const route = useHashRoute();
  const section = SECTIONS.has(route.section) ? route.section : "deliveries";
  const id = route.id !== null && route.id !== "" && Number.isFinite(Number(route.id))
    ? Number(route.id)
    : null;
  const ledgerBack = ledgerBackTarget(route.params);
  const ledgerFarmer = route.params.get("farmer") ?? "";
  const initialLedgerFarmer = /^\d+$/.test(ledgerFarmer) ? ledgerFarmer : "";

  let content: ReactNode;
  if (section === "deliveries") {
    content =
      id !== null ? (
        <DeliveryDetail
          deliveryId={id}
          onBack={() => navigate(ledgerBack ?? "#/deliveries")}
        />
      ) : (
        <DeliveriesScreen />
      );
  } else if (section === "prices") {
    content = <PricesScreen />;
  } else if (section === "payouts") {
    content =
      id !== null ? (
        <PayoutDetail
          payoutId={id}
          onBack={() => navigate(ledgerBack ?? "#/payouts")}
        />
      ) : (
        <PayoutsScreen />
      );
  } else {
    content = <LedgerScreen initialFarmerId={initialLedgerFarmer} />;
  }

  return <AppShell active={section}>{content}</AppShell>;
}

export default App;
