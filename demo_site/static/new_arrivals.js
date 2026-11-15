// 新着商品を API から取得して描画する（HTML だけを取得しても商品は含まれない）
fetch("/api/new-arrivals")
  .then(function (res) { return res.json(); })
  .then(function (items) {
    var ul = document.getElementById("arrivals");
    items.forEach(function (p) {
      var li = document.createElement("li");
      li.className = "product-card";
      li.setAttribute("data-product-id", p.id);
      var name = document.createElement("span");
      name.className = "name";
      name.textContent = p.name;  // textContent で入れ、HTML として解釈させない
      var price = document.createElement("span");
      price.className = "price";
      price.textContent = "¥" + p.price.toLocaleString("ja-JP");
      var stock = document.createElement("span");
      stock.className = "stock";
      stock.textContent = p.stock;
      li.append(name, " ", price, " ", stock);
      ul.appendChild(li);
    });
    document.getElementById("loading").remove();
  });
