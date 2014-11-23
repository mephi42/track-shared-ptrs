#include <iostream>
#include <memory>

struct A;
struct B;

struct A {
    std::shared_ptr<B> b;
};

struct B {
    std::shared_ptr<A> a;
};

int main() {
    auto a = std::make_shared<A>();
    auto b = std::make_shared<B>();
    std::weak_ptr<B> wb(b);
    a->b = wb.lock();
    b->a = a;
    a.reset();

    auto a1 = std::make_shared<A>();
    std::cerr << "&a1=" << &a1 << std::endl;
    std::weak_ptr<A> wa1(a1);
    a1.reset();
    a1 = wa1.lock();
}